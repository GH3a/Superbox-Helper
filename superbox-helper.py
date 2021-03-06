#!/usr/bin/python3

import argparse
import logging as log
from time import time_ns
import requests
from hashlib import md5
from base64 import b64encode
from simplejson.errors import JSONDecodeError
from json import loads, dumps

p_desc = 'Automates some basic functionality of Turkcell Superbox'
p_fmt = argparse.ArgumentDefaultsHelpFormatter

parser = argparse.ArgumentParser(description=p_desc, formatter_class=p_fmt)
parser.add_argument('router_ip', nargs='?', default='192.168.1.1',
                    help='IP address of the gateway')
parser.add_argument('username', nargs='?', default='admin',
                    help='user name to be used for authentication')
parser.add_argument('password',
                    help='password to be used for authentication')
parser.add_argument('--verbose', '-v', action='count', default=0)

args = parser.parse_args()

# https://patorjk.com/software/taag/#p=display&h=3&v=3&f=Slant
art = r'''
   _____                       __
  / ___/__  ______  ___  _____/ /_  ____  _  __
  \__ \/ / / / __ \/ _ \/ ___/ __ \/ __ \| |/_/
 ___/ / /_/ / /_/ /  __/ /  / /_/ / /_/ _>  <
/_____\____/ .___/\___/_/  /_.___/\____/_/|_|
   / / / _/_/ / /___  ___  _____
  / /_/ / _ \/ / __ \/ _ \/ ___/
 / __  /  __/ / /_/ /  __/ /
/_/ /_/\___/_/ .___/\___/_/  v0.1
            /_/
'''


class Superbox:
    def __init__(self, ip_, username_, password_, verbose_: bool):
        self.ip = ip_
        self.user = username_
        self.pw = password_
        self.verbose = verbose_

        if (self.verbose):
            log.basicConfig(
                format='[%(levelname)s] %(message)s', level=log.INFO)
            self.print_input_args()
        else:
            log.basicConfig(format='[%(levelname)s] %(message)s')

        self.logged_in = self.login()

        if self.logged_in:
            log.info('Successfully logged in.')
        else:
            log.error('Could not log in.')

    class AuthenticationResult:
        '''Possible values for \"LOGIN_MULTI_USER\"

        Found by trial and error. These are not confirmed values.
        There may be more status codes.'''
        invalid_json_key = 'null'
        missing_post_parameter = 'failure'
        success = '0'
        wrong_credentials_or_temporary_ban = '1'

    class SMSType:
        '''Possible values for SMS \"tags\"

        Found by trial and error. These are not confirmed values.'''
        read = '0'
        unread = '1'
        sent = '2'
        all = '10'

    def print_input_args(self):
        print(art)
        log.info('Input arguments')
        log.info('\tRouter IP: {}'.format(self.ip))
        log.info('\tUsername: {}'.format(self.user))
        log.info('\tPassword: {}'.format(self.pw))

    def initiate_session(self):
        '''Initiate a requests session and execute a basic test.'''
        self.router_URL = 'http://{}'.format(self.ip)

        self.s = requests.Session()

        # a dumb way to test connection
        log.info('Test connection by fetching router index page...')
        r = self.s.get(self.router_URL)

        if r.status_code == requests.codes.ok:
            log.info('Successfully fetched index page of the router.')
        else:
            log.error('Could not get index page of the router.')

        r.raise_for_status()

    def get_epoch(self):
        return(int(time_ns() / 1000000))

    def get_cmd(self, cmds: set, payload=None):
        # router return empty response for some parameters
        # when Referer is omitted from the headers
        self.s.headers.update(
            {'Referer': 'http://{}/index.html'.format(self.ip)})

        # concatenate commands into one variable if there's
        # more than one and 'multi_data' parameter should be
        # set to '1' when multiple values are requested.
        if len(cmds) > 1:
            cmd = ','.join(cmds)
            multi_data = '1'
        else:
            (cmd,) = cmds
            multi_data = None

        # 'isTest' and '_' parameters were always present while sending
        # a standard cmd request so I thought it's better to include them.
        # removing them did no harm but I do not want any surprise happen.
        default_payload = {'multi_data': multi_data,
                           'cmd': cmd, 'isTest': 'false', '_': self.get_epoch()}

        if payload == None:
            standart_request = True
            payload = default_payload
        else:
            standart_request = False
            payload.update(default_payload)

        r = self.s.get('http://{}/goform/goform_get_cmd_process'.format(self.ip),
                       params=payload)

        try:
            json_response = r.json()
        except JSONDecodeError as e:
            log.warning('Could not decode JSON gracefully.')
            log.warning(e)
            log.warning('Forcing another method to decode JSON...')
            json_response = loads(r.content, strict=False)

        # log data only at simple requests. things get complicated otherwise.
        if json_response and standart_request:
            log.info('get_cmd()')
            for command in cmd.split(','):
                log.info('\t{}: {}'.format(
                    command, json_response.get(command)))

        if multi_data or not standart_request:
            return(json_response)
        else:
            # no need to return a json object when only one parameter is requested
            return(json_response.get(cmd))

    def set_cmd(self, goformId: str, payload: set):
        # re-auth. idk why it is necessary.
        self.authenticate()

        payload.update(
            {'isTest': 'false', 'goformId': goformId, 'AD': self.AD})
        print(payload)
        r = self.s.post('http://{}/goform/goform_set_cmd_process'.format(self.ip),
                        data=payload)

        return(r)

    def compose_AD(self):
        '''Calculate AD digest after retrieving the required parameters'''

        params = self.get_cmd({'RD', 'wa_inner_version', 'cr_version'})

        RD = params['RD']
        rd0 = params['wa_inner_version']
        rd1 = params['cr_version']

        log.info('Get required parameters and compose AD digest...')

        rd = rd0 + rd1

        rd_md5 = md5(rd.encode()).hexdigest()
        ad = rd_md5 + RD
        AD = md5(ad.encode()).hexdigest()

        return(AD)

    def authenticate(self):
        '''Do the authentication'''
        self.AD = self.compose_AD()

        self.s.headers.update(
            {'Referer': 'http://{}/index.html'.format(self.ip),
             'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})

        pw_b64 = b64encode(self.pw.encode()).decode()

        payload = {'isTest': 'false', 'goformId': 'LOGIN_MULTI_USER',
                   'user': self.user, 'password': pw_b64, 'AD': self.AD}
        r = self.s.post('http://{}/goform/goform_set_cmd_process'.format(self.ip),
                        data=payload)

        auth_result = r.json()['result']
        return(auth_result)

    def login(self):
        self.initiate_session()
        auth_result = self.authenticate()

        login_verified = False

        if auth_result == self.AuthenticationResult.invalid_json_key:
            log.error('Authentication failed: Invalid JSON key.')
        elif auth_result == self.AuthenticationResult.missing_post_parameter:
            log.error('Authentication failed: Missing POST parameter(s)')
            log.error('Please check "payload" variable of "authenticate()"')
        elif auth_result == self.AuthenticationResult.success:
            log.info('Authentication succeeded.')
        elif auth_result == self.AuthenticationResult.wrong_credentials_or_temporary_ban:
            log.error(
                'Authentication failed: Invalid credentials or temporary ban')
            log.error('Either wrong credentials are provided or too many failed')
            log.error('login attempts caused a temporary login ban.')
        else:
            log.error(
                'Authentication failed: Unexpected result ({})'.format(auth_result))

        if auth_result == self.AuthenticationResult.success:
            # "wifi_lbd_enable" returns an empty response before login and
            # "1" after login, so we can use it for a lame login verification.
            login_verified = self.get_cmd({'wifi_lbd_enable'}) == '1'

            if not login_verified:
                log.warning('Could not verify login.')
                log.warning('This may be nonsense but be careful.')

            return(True)
        else:
            return(False)

    def get_sms(self, amount='500', tags='0'):
        # maximum default amount was 500.
        # amount must be a multiple of 10

        # todo: decode content. hint: decodeMessage and hex2char @ util.js

        raw_result = self.get_cmd({'sms_data_total'},
                                  {'page': '0', 'data_per_page': amount,
                                   'mem_store': '1', 'tags': tags,
                                   'order_by': 'order+by+id+desc'})
        result = raw_result.get('messages')

        if len(result):
            log.info('get_sms()')
            log.info(dumps(result, indent=4, sort_keys=True))

        return(result)

    def remove_sms(self, ids: set):
        n = ';'.join(ids) + ';'
        payload = {'msg_id': n, 'notCallback': 'true'}
        raw_result = self.set_cmd('DELETE_SMS', payload)
        result = raw_result.json().get('result')

        log.info('remove_sms()')
        log.info('\tn: "{}"'.format(n))
        log.info('\tresult: {}'.format(result))

        if result == 'success':
            return(True)
        elif result == 'failure':
            return(False)
        else:
            return(None)


if __name__ == '__main__':
    superbox = Superbox(args.router_ip, args.username,
                        args.password, args.verbose)

    # messages = superbox.get_sms(Superbox.SMSType.read)
    # messages = superbox.get_sms(Superbox.SMSType.unread)
    # messages = superbox.get_sms(Superbox.SMSType.sent)
    messages = superbox.get_sms('10', Superbox.SMSType.all)
    # messages = superbox.remove_sms({'152', '154', '155'})
