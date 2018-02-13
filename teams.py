
import random
import asyncio
import itertools
import requests
import re

from pprint import pprint
from aiohttp import ClientSession

from IPython import embed

from bs4 import BeautifulSoup

from datetime import datetime, timedelta

activity_url_template = "https://amara.org/en/teams/{}/activity/"

component_mapping = {
    'year': timedelta(weeks=52.25), 
    'month': timedelta(weeks=4.34524),
    'week': timedelta(weeks=1),
    'day': timedelta(days=1), 
    'hour': timedelta(hours=1), 
    'minute': timedelta(minutes=1)
}

TIME_THRESHOLD = -60 * 10 # time cutoff for interesting events in seconds (10 minutes)
ALERT_TERMS = ['added a video', 'unassigned', r"endorsed.*(transcriber)"] # What terms should trigger an alert
#ALERT_TERMS = ['added a video', 'unassigned', 'endorsed'] # What terms should trigger an alert
ALERT_REGEX = re.compile("|".join(ALERT_TERMS))

def timestring_to_minutes_delta(string):
    """ Parses e.g. 1 day, 5 hours ago as time delta"""

    def comp_to_delta(str_):
        """comp_to_delta('5 hours') returns datetime.timedelta(18000),"""
        str_ = str_.replace('ago','').strip().rstrip('s')
        numerator, comp = str_.split(' ')
        return int(numerator) * component_mapping[comp]

    delta = -sum([comp_to_delta(c) for c in string.split(',')], timedelta())
    return delta



async def auth_session_and_fetch_teams(session):

    url = "https://amara.org/en/auth/login/?next=/"
    username = '';
    password = '';

    teams = []
    
    async with session.get(url) as response:
        await response.read()

        crsf = response.cookies.get('csrftoken').value

    auth = {'csrfmiddlewaretoken':crsf, 'username': username,'password': password}
    ref = {'referer':'https://amara.org/en/auth/login/?next=/'}

    async with session.post("https://amara.org/en/auth/login_post/", data=auth, headers=ref) as response:
        
        doc = await response.text()
        
        #teams.append({'name':'ondemand-328-ct', 'path':'ondemand-328-ct'})

        soup = BeautifulSoup(doc, 'html.parser')
        menu = soup.find(id='user-menu')

        for candidate in menu.find_next_sibling('ul').find_all('a'):

            if not candidate['href'].startswith('/en/teams/'):
                continue

            name = candidate['href'].split('/')[-2]

            if name == 'my': # Ignore the paged teams listings link.
                continue

            teams.append({'path': candidate['href'], 'name': name})

        return teams


async def fetch_team_activities(url, team, session):

    async with session.get(url) as response:

        doc = await response.text()

        soup = BeautifulSoup(doc, 'html.parser')
        activity = soup.find(id='activity-list')

        activities = []

        for item, time in [ (x, x.find(class_='timestamp').text) for x in activity.find_all('li')]:

            _delta = timestring_to_minutes_delta(time)

            if _delta.total_seconds() < TIME_THRESHOLD: #don't bother with tasks older than 20 minutes
                break
                                        
            activities.append({
                'team': team,
                'url': url,
                'delta': _delta, 
                'activity': {
                    'time':time,
                    'text':item.text,
                    # 'body':item.prettify(),
                }
            })


        return activities


async def bound_fetch(sem, url, team, session):
    async with sem:
        return await fetch_team_activities(url, team, session)


async def main():        
    print(datetime.now())        
    tasks = []
    sem = asyncio.Semaphore(1)


    # Create client session that will ensure we dont open new connection
    # per each request.
    async with ClientSession() as session:

        teams = await auth_session_and_fetch_teams(session)

        pprint("Total teams to scrape: {}".format(len(teams)))

        for team in teams:

            url = activity_url_template.format(team['name'])
            task = asyncio.ensure_future(bound_fetch(sem, url, team, session))
            tasks.append(task)

        # Gather all futures
        teams_activities = asyncio.gather(*tasks)

        # Flatten nested activities.    
        activities = list(itertools.chain(*await teams_activities))
        
        #embed()
        pprint("Total activities before filtering: {}".format(len(activities)))

        # Filter by terms
        activities = list(filter(lambda a: ALERT_REGEX.search(a['activity']['text']), activities))

        # -timedelta(minutes=60)
        if len(activities) > 0:
            team_names = list(set(map(lambda a: a['team']['name'], activities)))
            sms_message = ";".join(team_names)
            email_message = ''
            for a in activities:
                email_message += "Team: {}, URL: {}\n".format(a['team']['name'], a['url'])
                
            url = 'https://maker.ifttt.com/trigger/amara/with/key/i2KFblN2MQUjVcHBV6Un6BpWuoDjUbUsNeIjmlloq2q'
            payload = {"value1":sms_message, "value2":email_message}
            r = requests.post(url,json=payload)
            pprint("message sent: {}, response received: {}".format(payload,r))
            
        pprint("Total activities after filtering: {}".format(len(activities)))
        pprint(activities[:10])


loop = asyncio.get_event_loop()
future = asyncio.ensure_future(main())
loop.run_until_complete(future)
