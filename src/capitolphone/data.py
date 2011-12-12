from flask import g
from influenceexplorer import InfluenceExplorer
# from realtimecongress import RTC
from sunlightapi import sunlight

from capitolphone import settings

TITLES = {
    'Rep': 'Representative',
    'Sen': 'Senator',
}

# RTC.apikey = settings.SUNLIGHT_KEY
sunlight.apikey = settings.SUNLIGHT_KEY
ie = InfluenceExplorer(settings.SUNLIGHT_KEY)

def load_call(sid, params):
    
    doc = g.db.calls.find_one({'call_sid': sid})
    
    if doc is None:
        doc = {
            'call_sid': sid,
            'from': params['From'],
            'to': params['To'],
            'caller_name': params.get('CallerName', None),
            'context': {
                'zipcode': None,
                'legislator': None,
            },
        }
        g.db.calls.insert(doc)
    
    if 'requests' not in doc:
        doc['requests'] = []
    
    doc['requests'].append({
        'timestamp': g.now,
        'call_status': params['CallStatus']
    })
    
    doc['current_status'] = params['CallStatus']
    
    return doc

def legislators_for_zip(zipcode):
    
    doc = g.db.legislatorsByZipcode.find_one({'zipcode': zipcode})
    
    if doc is None:
        
        results = sunlight.legislators.allForZip(zipcode)
        
        legislators = [r.__dict__.copy() for r in results]
        legislators.sort(lambda x, y: -cmp(x['title'], y['title']))
        
        for l in legislators:
            l['short_title'] = l['title']
            l['title'] = TITLES.get(l['title'], 'Representative')
            l['fullname'] = "%s %s %s" % (l['title'], l['firstname'], l['lastname'])
        
        g.db.legislatorsByZipcode.insert({
            'timestamp': g.now,
            'zipcode': zipcode,
            'legislators': legislators,
        })
        
    else:
        legislators = doc['legislators']
    
    return legislators