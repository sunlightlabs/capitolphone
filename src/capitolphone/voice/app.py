from functools import wraps
import datetime

from flask import Flask, Response, abort, g, request
from twilio import twiml
from twilio.util import RequestValidator
import pymongo

from capitolphone import data, settings

app = Flask(__name__)

def twilioify(func):
    """
        This decorator method is used to validate Twilio calls
        and create the call context in the request.
    """
    
    @wraps(func)
    def decorated(*args, **kwargs):
            
        if 'CallSid' not in request.form:
            return abort(404)

        validator = RequestValidator(settings.AUTH_TOKEN)
        sig_header = request.headers.get('X-Twilio-Signature', '')

        # validator params are called URL, POST vars, and signature
        if not validator.validate(request.base_url, request.form, sig_header):
            return abort(401)
        
        # load the call from Mongo or create if one does not exist
        g.call = data.load_call(request.form['CallSid'], request.form)
                
        return func(*args, **kwargs)
        
    return decorated

@app.before_request
def before_request():
    g.now = datetime.datetime.utcnow()
    g.conn = pymongo.Connection()
    g.db = g.conn.capitolphone

@app.after_request
def after_request(response):
    if hasattr(g, 'call') and g.call is not None:
        g.db.calls.save(g.call)
    return response
    
@app.teardown_request
def teardown_request(exception):
    g.conn.disconnect()

@app.route("/voice", methods=['GET','POST'])
@twilioify
def call_init():
    
    now = datetime.datetime.utcnow()

    r = twiml.Response()
    r.say("Welcome to CapitolPhone brought to you by the Sunlight Foundation.")
    with r.gather(numDigits=5, action='/voice/zipcode') as rg:
        rg.say("In order to locate your representatives, please enter your five digit zipcode now.")
        
    return Response(str(r), mimetype='application/xml')

@app.route("/voice/zipcode", methods=['POST'])
@twilioify
def zipcode():
    
    zipcode = request.form.get('Digits', None)
    r = twiml.Response()
    
    if zipcode == '00000':
    
        r.say("""
            Welcome to movie phone.
            You seem like the type of person that would enjoy The Twilight Saga: Breaking Dawn Part 1.
            The best showings are during the day, but you'll be stuck in middle school.
            Ha ha ha. Loser.
        """)
    
    else:
    
        g.call['context']['zipcode'] = zipcode
    
        legislators = data.legislators_for_zip(zipcode)
        
        if legislators:
    
            options = [(l['fullname'], l['bioguide_id']) for l in legislators]
            script = ". ".join("Press %i for %s" % (index + 1, o[0]) for index, o in enumerate(options))
    
            msg = "Please select from the following list of legislators."
            if len(legislators) > 3:
                msg = """
                    Since your zipcode covers more than one congressional district,
                    I will provide you with a list of all possible legislators
                    that may represent you. %s
                """ % msg
    
            r.say(msg)
            with r.gather(numDigits=5, action='/voice/reps') as rg:
                rg.say(script)
            
        else:
            
            r.say("I'm sorry, I wasn't able to locate any representatives for %s." % (" ".join(zipcode),))
            with r.gather(numDigits=5, action='/voice/zipcode') as rg:
                rg.say("Please try again or enter a new zipcode.")
        
    return Response(str(r), mimetype='application/xml')

@app.route("/voice/reps", methods=['POST'])
@twilioify
def reps():
    
    if 'Digits' in request.form:
        selection = int(request.form.get('Digits', None)) - 1
        l = data.legislators_for_zip(g.call['context']['zipcode'])[selection]    
        g.call['context']['legislator'] = l
    
    r = twiml.Response()
    r.say("Thank you.")
    with r.gather(numDigits=1, action='/voice/rep') as rg:
        rg.say("""
            Press 1 to hear recent votes.
            Press 2 to hear top campaign donors.
            Press 9 to be connected directly to your representatives office.
        """)
        
    return Response(str(r), mimetype='application/xml')

@app.route("/voice/rep", methods=['POST'])
@twilioify
def rep():
    
    selection = request.form.get('Digits', None)
    
    r = twiml.Response()
    
    l = g.call['context']['legislator']
    
    if selection == '1':
        pass
    
    elif selection == '9':
        
        # connect to the member's office
        
        r.say("After a brief pause, we will connect you with the office of %s. Thank you for using CapitolPhone!" % l['fullname'])
        with r.dial() as rd:
            rd.number(l['phone'])
    
    else:
        r.say("That's all I have for now. %s" % l['fullname'])
        r.redirect('/voice/reps')
    
    return Response(str(r), mimetype='application/xml')


if __name__ == "__main__":
    app.run(debug=True)