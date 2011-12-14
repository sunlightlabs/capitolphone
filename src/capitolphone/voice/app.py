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

        g.zipcode = g.call['context'].get('zipcode', None)
        g.legislator = g.call['context'].get('legislator', None)

        twilio_response = func(*args, **kwargs)

        return Response(str(twilio_response), mimetype='application/xml')

    return decorated

@app.before_request
def before_request():
    """ Setup request context by setting current request time (UTC),
        creating MongoDB connection and reference to collection.
    """
    g.now = datetime.datetime.utcnow()
    g.conn = pymongo.Connection()
    g.db = g.conn.capitolphone

@app.after_request
def after_request(response):
    """ Save the call object from the request context if one exists.
    """
    if hasattr(g, 'call') and g.call is not None:
        g.db.calls.save(g.call)
    return response

@app.teardown_request
def teardown_request(exception):
    """ Disconnect from the MongoDB instance.
    """
    g.conn.disconnect()

@app.route("/voice", methods=['GET','POST'])
@twilioify
def call_init():
    """ Initiate a new call. Welcomes the user and prompts for zipcode.
    """

    r = twiml.Response()
    #r.say("Welcome to CapitolPhone brought to you by the Sunlight Foundation.")
    #with r.gather(numDigits=5, timeout=10, action='/voice/zipcode') as rg:
        #rg.say("In order to locate your representatives, please enter your five digit zipcode now.")

    r.play("http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/intro.wav")
    r.gather(numDigits=5, timeout=10, action='/voice/zipcode')

    return r

@app.route("/voice/zipcode", methods=['POST'])
@twilioify
def zipcode():
    """ Handles POSTed zipcode and prompts for legislator selection.
    """

    zipcode = request.form.get('Digits', g.zipcode)
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
            script = " ".join("Press %i for %s." % (index + 1, o[0]) for index, o in enumerate(options))
            script += " Press 0 to enter a new zipcode."

            if len(legislators) > 3:
                r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/selectlegalt.wav')
            else:
                r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/selectleg.wav')

            with r.gather(numDigits=1, timeout=10, action='/voice/reps') as rg:
                rg.say(script)

        else:

            r.say("I'm sorry, I wasn't able to locate any representatives for %s." % (" ".join(zipcode),))
            with r.gather(numDigits=5, timeout=10, action='/voice/zipcode') as rg:
                rg.say("Please try again or enter a new zipcode.")

    return r

@app.route("/voice/reps", methods=['POST'])
@twilioify
def reps():

    r = twiml.Response()

    if 'Digits' in request.form:

        digits = request.form.get('Digits', None)

        if digits == '0':

            r.redirect('/voice')
            return r # shortcut the process and start over

        else:

            selection = int(digits) - 1
            legislator = data.legislators_for_zip(g.zipcode)[selection]
            g.call['context']['legislator'] = legislator

    else:
        legislator = g.legislator

    r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/mainmenu-intro.wav')
    r.say('%s' % legislator['fullname'])
    with r.gather(numDigits=1, timeout=30, action='/voice/rep') as rg:
        rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/mainmenu.wav')

    return r

def handle_selection(selection):

    r = twiml.Response()

    if selection == '1':

        contribs = data.top_contributors(g.legislator)
        script = " ".join("%(name)s contributed $%(total_amount)s.\n" % c for c in contribs)

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/1.wav')
        r.say(script)

        with r.gather(numDigits=1, timeout=10, action='/voice/next/2') as rg:
            rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/1-out.wav')

    elif selection == '2':

        votes = data.recent_votes(g.legislator)

        script = " ".join("On %(question)s. Voted %(voted)s. . The bill %(result)s.\t" % v for v in votes)

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/2.wav')
        r.say("%s. %s" % (g.legislator['fullname'], script))

        with r.gather(numDigits=1, timeout=10, action='/voice/next/3') as rg:
            rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/2-out.wav')

    elif selection == '3':

        bio = data.legislator_bio(g.legislator)

        r.say(bio or ('Sorry, we were unable to locate a biography for %s' % g.legislator['fullname']))

        with r.gather(numDigits=1, timeout=10, action='/voice/next/4') as rg:
            rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/3-out.wav')

    elif selection == '4':

        comms = data.committees(g.legislator)

        r.say(g.legislator['fullname'])
        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/4.wav')
        r.say(comms)

        with r.gather(numDigits=1, timeout=10, action='/voice/next/5') as rg:
            rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/4-out.wav')

    elif selection == '5':

        # connect to the member's office

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/5-pre.wav')
        r.say(g.legislator['fullname'])
        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/5-post.wav')

        with r.dial() as rd:
            rd.number(g.legislator['phone'])

    elif selection == '9':

        with r.gather(numDigits=1, timeout=10, action='/voice/signup') as rg:
            rg.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/9.wav')

    elif selection == '0':
        r.redirect('/voice/zipcode')

    else:
        r.say("I'm sorry, I don't recognize that selection. I will read you the options again.")
        r.redirect('/voice/reps')

    return r

@app.route("/voice/rep", methods=['POST'])
@twilioify
def rep():
    selection = request.form.get('Digits', None)
    return handle_selection(selection)

@app.route("/voice/next/<next_selection>", methods=['POST'])
@twilioify
def next(next_selection):
    selection = request.form.get('Digits', None)
    if selection == '1':
        return handle_selection(next_selection)
    else:
        r = twiml.Response()
        r.redirect('/voice/reps')
        return r

@app.route("/voice/signup", methods=['POST'])
@twilioify
def signup():

    r = twiml.Response()

    selection = request.form.get('Digits', None)

    if selection == '1':

        g.db.smsSignups.insert({
            'url': g.call['from'],
            'timestamp': g.now,
        })

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/9-1.wav')

        r.redirect('/voice/reps')

    elif selection == '2':

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/9-2.wav')
        r.record(action='/voice/message', timeout=10, maxLength=120)
        r.redirect('/voice/reps')

    elif selection == '3':

        r.play('http://assets.sunlightfoundation.com/projects/transparencyconnect/audio/9-3.wav')
        r.redirect('/voice/reps')

    else:
        r.redirect('/voice/reps')

    return r

@app.route("/voice/message", methods=['POST'])
@twilioify
def message():
    g.db.messages.insert({
        'url': request.form['RecordingUrl'],
        'timestamp': g.now,
    })
    r = twiml.Response()
    r.redirect('/voice/reps')
    return r

@app.route("/test", methods=['GET'])
def test_method():
    r = data.recent_votes({'bioguide_id': 'V000128'})
    return str(r)

if __name__ == "__main__":
    app.run(debug=True)