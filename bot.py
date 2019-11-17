import datetime
import os
import pickle
import random
import re
import requests
import sched
import sys
import time
import urllib.parse

from bs4 import BeautifulSoup
from python3_anticaptcha import NoCaptchaTaskProxyless

from cities import Cities
from logger import Logger
from months import months
from vk_bots import bots
from vk_groups import groups
import settings


class SkynetBot:

    ACTION_ONLINE = 'online'
    ACTION_ADD_FRIEND = 'add_friend'
    ACTION_CHECK_FRIENDS = 'check_friends'
    ACTION_SEND_STAT = 'send_stat'
    ACTION_VISIT_GROUP = 'visit_group'
    ACTION_REPOST_OUR = 'repost_our'
    ACTION_REPOST_RANDOM = 'repost_random'

    admin_vk_id = None
    antigate_key = None
    rucaptcha_key = None

    vk_id = None
    vk_username = None
    vk_password = None
    vk_my_group = None

    _actions_periods = {
        ACTION_ONLINE: 60 * 7,
        ACTION_ADD_FRIEND: 60 * 45,
        ACTION_CHECK_FRIENDS: 60 * 25,
        ACTION_SEND_STAT: 60 * 60 * 20,
        ACTION_VISIT_GROUP: 60 * 60 * 7,
        ACTION_REPOST_OUR: 60 * 60 * 10,
        ACTION_REPOST_RANDOM: 60 * 60 * 12,
    }

    _reposts_min_periods = {
        'our_post': 60 * 60 * 20,
        'random_post': 60 * 60 * 65
    }

    _actions_timestamps = {
        ACTION_ONLINE: 0,
        ACTION_ADD_FRIEND: 0,
        ACTION_CHECK_FRIENDS: 0,
        ACTION_SEND_STAT: 0,
        ACTION_VISIT_GROUP: 0,
        ACTION_REPOST_OUR: 0,
        ACTION_REPOST_RANDOM: 0,
    }
    _cities = None
    _logger = None
    _session = None

    def __init__(self, **kwargs):
        self.admin_vk_id = kwargs['admin_vk_id']
        self.antigate_key = kwargs['antigate_key']
        self.rucaptcha_key = kwargs['rucaptcha_key']
        self.vk_username = kwargs['username']
        self.vk_password = kwargs['password']
        self.vk_my_group = kwargs['vk_my_group']
        self._cities = Cities()
        if 'logger' in kwargs:
            self._logger = kwargs['logger']

    def add_friend(self):
        """
        Find a friend and send him a request
        :return: bool

        """
        self._log('run add_friend')
        if self._open_main_page():
            friend_id, friend_hash = self._search_friend()
            if not friend_id or not friend_hash:
                self._log('error: not friend_id or not friend_hash')
                return False

            def send_friend_request(fr_id, fr_hash, captcha_res=None):
                params = {
                    'act': 'subscr',
                    'al': 1,
                    'from': 'search',
                    'hash': fr_hash,
                    'oid': fr_id,
                    'ref': 'friends'
                }
                if captcha_res:
                    params['recaptcha'] = captcha_res
                time.sleep(3)
                response = self._post('https://vk.com/al_feed.php', data=params)
                return response

            r = send_friend_request(friend_id, friend_hash)

            if re.match('(.*)Вы подписались', r.text):
                self._save_session()
                self._log('a friend ' + str(friend_id) + ' added successfully')
                return True
            if re.match('(.*)<!>ru', r.text):
                try:
                    captcha_key = re.search('(.+)<!>2<!>(.+)<!>2<!>ru', r.text).group(2)
                except AttributeError:
                    self._log('error: AttributeError captcha_key regex')
                    return False

                captcha_response = self._solve_captcha(captcha_key)
                if not captcha_response:
                    self._log('error: not captcha_response')
                    return False

                r = send_friend_request(friend_id, friend_hash, captcha_response)
                if re.match('(.*)Вы подписались', r.text):
                    self._save_session()
                    self._log('a friend ' + str(friend_id) + ' added successfully')
                    return True
                self._log('error: add_friend regex')
                return False

            self._log('error: send_friend_request regex')
            return False

        self._log('error: add_friend')
        return False

    def check_action_timestamp(self, action_name):
        """
        Check if action_timestamp is older than timeout

        example of usage:
        if bot.check_action_timestamp(bot.ACTION_ADD_FRIEND):
            action = bot.add_friend()

        :param action_name: str
        :return: bool

        """
        now = time.time()
        timeout = self._actions_periods[action_name]
        return now - self._actions_timestamps[action_name] >= timeout

    def check_friends(self):
        """
        Check the income friendship quotes and accept one
        :return: bool

        """
        self._log('run check_friends')
        if self._open_main_page():
            time.sleep(3)
            r = self._get('https://vk.com/friends?section=requests')
            buttons = re.findall(
                '<button([^>]*)accept_request_([0-9]+)([^>]*)Friends.acceptRequest\(([0-9]+), \'([^>]*)\', this\)">Добавить в друзья</button>',
                r.text)
            if not len(buttons):
                self._log('check_friends completed successfully, accepted %d' % 0)
                return True
            html_trash, friend_id, html_trash, html_trash, friend_hash = buttons[0]

            params = {
                'act': 'add',
                'al': 1,
                'hash': friend_hash,
                'mid': int(friend_id),
                'request': 1,
                'select_list': 1
            }

            time.sleep(3)
            r = self._post('https://vk.com/al_friends.php', data=params)

            if re.match('(.*)у Вас в друзьях(.*)', r.text):
                self._save_session()
                self._log('check_friends completed successfully, accepted %d' % 1)
                return True

        self._log('error: check_friends')
        return False

    def get_online(self):
        """
        Open the profile page to refresh online status
        :return: bool

        """
        self._log('run get_online')
        if self._open_main_page():
            time.sleep(3)
            r = self._get('https://vk.com/id'+self.vk_id)
            if r.status_code == 200:
                self._save_session()
                self._log('status online updated sucessfully')
                return True

        self._log('error: get_online')
        return False

    def repost_our_post(self):
        """
        Check if there is a new post in our group post it
        with 1 random post interval and _reposts_min_periods['our_post'] interval
        :return: bool

        """
        self._log('run repost_our_post')
        if not self._open_main_page():
            return False

        time.sleep(3)
        r = self._get('https://vk.com/id' + self.vk_id)
        if r.status_code != 200:
            return False

        last_bot_post_age = self._get_bot_last_post_age(r)
        now = time.time()
        if now - last_bot_post_age < self._reposts_min_periods['our_post']:
            return False

        last_my_group_post = self._get_last_my_group_post()
        already_reposted = self._check_post_already_reposted_by_bot(last_my_group_post)
        if already_reposted:
            return True

        last_bot_post = self._get_last_bot_post()
        if last_bot_post and last_bot_post['copy_author_link'] == '/buzovaofficial':
            self.repost_random_post(self._reposts_min_periods['our_post'])
        else:
            self._repost_post(last_my_group_post)
        return False

    def repost_random_post(self, interval=_reposts_min_periods['random_post']):
        """
        Repost a new post from _groups_list it with interval
        :return: bool

        """
        self._log('run repost_random_post')
        if not self._open_main_page():
            return False

        time.sleep(3)
        r = self._get('https://vk.com/id' + self.vk_id)
        if r.status_code != 200:
            return False

        last_bot_post_age = self._get_bot_last_post_age(r)
        now = time.time()
        if now - last_bot_post_age < interval:
            return False

        best_post = self._find_best_random_post()
        result = self._repost_post(best_post)
        return result

    def get_session(self):
        """
        The current Requests.session() getter
        :rtype: Session

        """
        if self._session is None:
            self._session = self._init_session()
        return self._session

    def send_stat(self):
        """
        Send a message with the current account parameters
        :return: bool

        """
        self._log('run send_stat')
        if self._open_main_page():
            time.sleep(3)
            r = self._get('https://vk.com/id' + self.admin_vk_id)
            if r.status_code == 200:
                try:
                    admin_hash = re.search('\\\\n    hash: \'([^\']+)\',\\\\n', r.text).group(1)
                    stat = self._collect_stat()
                    params = {
                        'act': 'a_send_box',
                        'al': 1,
                        'chas': admin_hash,
                        'entrypoint': 'writebox',
                        'from': 'box',
                        'media': '',
                        'message': 'Привет! ' + '/'.join(stat),
                        'title': '',
                        'to_ids': self.admin_vk_id
                    }
                    r = self._post('https://vk.com/al_im.php', data=params, allow_redirects=True)
                    if r.status_code == 200:
                        self._log('success: send_stat')
                        return True
                    return False
                except AttributeError:
                    self._log('error: send_stat')
                    return False

        self._log('error: send_stat _open_main_page')
        return False

    def update_action_timestamp(self, action_name):
        """
        Update action_timestamp to the current timestamp

        example of usage:
        bot.add_friend()
        bot.update_action_timestamp(bot.ACTION_ADD_FRIEND)

        :param action_name: str
        :return: bool

        """
        self._actions_timestamps[action_name] = time.time()
        return True

    def visit_group(self):
        """
        Just visit a group
        :return: bool

        """
        self._log('run visit_group')
        if self._open_main_page():
            r = self._get(self.vk_my_group)
            if r.status_code == 200:
                self._log('success: visit_group')
                return True
        self._log('error: visit_group')
        return False

    """
    Private functions

    """

    def _collect_stat(self):
        stat = []
        if self._open_main_page():
            time.sleep(3)
            r = self._get('https://vk.com/id'+self.vk_id)
            if r.status_code == 200:
                try:
                    soup = BeautifulSoup(r.text, "html.parser")

                    friends_count = '0'
                    friends_wrapper = soup.select_one('#profile_friends .header_count')
                    if friends_wrapper:
                        friends_count = friends_wrapper.getText()
                    stat.append(friends_count)

                    incoming_requests_count = '0'
                    incoming_wrapper = soup.select_one('#l_fr .left_count')
                    if incoming_wrapper:
                        incoming_requests_count = incoming_wrapper.getText()
                    stat.append(incoming_requests_count)

                    messages_count = '0'
                    messages_wrapper = soup.select_one('#l_msg .left_count')
                    if messages_wrapper:
                        messages_count = messages_wrapper.getText()
                    stat.append(messages_count)
                except:
                    pass

        return stat

    def _change_language(self, response):
        try:
            my_hash = re.search('lang_id: 0, hash: \'([^\']+)\'}', response.text).group(1)
            params = {
                'act': 'change_lang',
                'al': 1,
                'hash': my_hash,
                'lang_id': 0
            }
            r = self._post('https://vk.com/al_index.php', data=params, allow_redirects=True)
            if r.status_code == 200:
                return True
        except:
            pass
        return False

    def _check_post_already_reposted_by_bot(self, post):
        self._log('run _check_post_already_reposted_by_bot')

        try:
            time.sleep(3)
            r = self._get('https://vk.com/id' + self.vk_id)
            soup = BeautifulSoup(r.text, "html.parser")
            my_posts = soup.select('.wall_posts .post.own')
        except Exception as e:
            return False

        group_post_id = post['id'].replace('post', '').replace('-', '')
        for my_post in my_posts:
            my_post = self._parse_wall_post(my_post)
            if my_post['original_id'] is None:
                continue
            my_post_id = my_post['original_id'].replace('post', '').replace('-', '')
            if my_post_id == group_post_id:
                return True

        return False

    def _find_best_random_post(self):
        self._log('run _find_best_random_post')
        all_random_posts = self._get_all_random_posts()
        all_skynet_bots_posts = self._get_all_skynet_bots_posts()

        new_random_posts = []
        for random_post in all_random_posts:
            random_post_id = random_post['id'].replace('post', '').replace('-', '')
            already_reposted = False
            for skynet_bot_post in all_skynet_bots_posts:
                if not skynet_bot_post['original_id']:
                    continue
                bot_post_id = skynet_bot_post['original_id'].replace('post', '').replace('-', '')
                if bot_post_id == random_post_id:
                    already_reposted = True
            if not already_reposted:
                new_random_posts.append(random_post)

        result = sorted(new_random_posts, key=lambda k: k['rating'], reverse=True)
        result = result[:30]
        result = random.choice(result)
        return result

    def _get(self, *args, **kwargs):
        try:
            result = self.get_session().get(*args, **kwargs)
        except BrokenPipeError:
            self._log('BrokenPipeError, reinit session')
            self._init_session()
            result = self.get_session().get(*args, **kwargs)
        return result

    def _get_all_random_posts(self):
        self._log('run _get_all_random_posts')
        all_random_posts = []
        for group in groups:
            try:
                time.sleep(3)
                r = self._get(group)
                soup = BeautifulSoup(r.text, "html.parser")
                posts = soup.select('.post.own')
                for post in posts:
                    if not 'post_copy' in post.get('class') and not post.select_one('.wall_marked_as_ads'):
                        all_random_posts.append(post)
            except Exception as e:
                continue

        result = []
        for post in all_random_posts:
            result.append(self._parse_wall_post(post))
        return result

    def _get_all_skynet_bots_posts(self):
        self._log('run _get_all_skynet_bots_posts')
        all_skynet_bots_posts = []
        for bot_page in bots:
            try:
                time.sleep(3)
                r = self._get(bot_page)
                soup = BeautifulSoup(r.text, "html.parser")
                posts = soup.select('.wall_posts .post.own')
                for post in posts:
                    all_skynet_bots_posts.append(post)
            except Exception as e:
                continue

        result = []
        for post in all_skynet_bots_posts:
            result.append(self._parse_wall_post(post))
        return result

    def _get_bot_last_post_age(self, response):
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            last_post = soup.select_one('.post.own.post_copy')

            if not last_post:
                return 0

            post_data = self._parse_wall_post_date(last_post)
            return post_data
        except:
            pass
        return 0

    def _get_last_bot_post(self):
        try:
            time.sleep(3)
            r = self._get('https://vk.com/id' + self.vk_id)
            soup = BeautifulSoup(r.text, "html.parser")
            my_post = soup.select_one('.wall_posts .post.own')
        except Exception as e:
            return None

        my_post = self._parse_wall_post(my_post)
        return my_post

    def _get_last_my_group_post(self):
        r = self._get(self.vk_my_group)
        soup = BeautifulSoup(r.text, "html.parser")
        post = soup.select_one('.wall_posts .post.own')
        post = self._parse_wall_post(post)
        return post

    def _init_session(self):
        self._session = None
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
        }
        os.makedirs(os.path.dirname('tmp/vk_user_agent.out'), exist_ok=True)
        try:
            with open('tmp/vk_user_agent.out', 'r') as f:
                user_agent = f.read()
        except IOError:
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.3309.6 Safari/537.36' % random.randint(52, 65)
            with open('tmp/vk_user_agent.out', 'w') as f:
                f.write(user_agent)
        headers['user-agent'] = user_agent

        self._session = requests.session()
        self._session.headers.update(headers)
        os.makedirs(os.path.dirname('tmp/vk_cookies.out'), exist_ok=True)
        try:
            with open('tmp/vk_cookies.out', 'rb') as f:
                cookies = pickle.load(f)
                cookies = requests.utils.cookiejar_from_dict(cookies)
                self._session.cookies = cookies
        except IOError:
            pass

        return self._session

    def _log(self, msg):
        if self._logger:
            self._logger.log(msg)
            return True
        return False

    def _login(self, response):
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            ip_h = soup.find('input', {'name': 'ip_h'}).get('value')
            lg_h = soup.find('input', {'name': 'lg_h'}).get('value')

            params = {
                'act': 'login',
                'role': 'al_frame',
                '_origin': 'https://vk.com',
                'ip_h': ip_h,
                'lg_h': lg_h,
                'email': self.vk_username,
                'pass': self.vk_password
            }

            time.sleep(3)
            r = self._post('https://login.vk.com/', data=params, allow_redirects=False)
            location = r.headers['location']

            parsed_location = urllib.parse.urlparse(location)
            parsed_location = urllib.parse.parse_qs(parsed_location.query)

            if 'sid' in parsed_location:
                captcha_response = self._solve_captcha(parsed_location['sid'])
                if not captcha_response:
                    return False
                params['recaptcha'] = captcha_response

                time.sleep(3)
                r = self._post('https://login.vk.com/', data=params, allow_redirects=False)
                location = r.headers['location']
                parsed_location = urllib.parse.urlparse(location)
                parsed_location = urllib.parse.parse_qs(parsed_location.query)

            if '__q_hash' in parsed_location:
                time.sleep(3)
                r = self._get(location)

                try:
                    self.vk_id = re.search('"uid":"([0-9]+)"', r.text).group(1)
                except AttributeError:
                    pass
                self._save_session()
                return True
            else:
                return False

        except Exception as e:
            pass
        return False

    def _needs_change_language(self, response):
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            html = soup.find(name="html", attrs={'lang': 'ru'})
            if html:
                return False
            return True
        except Exception as e:
            return True

    def _needs_login(self, response):
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            ip_h = soup.find('input', {'name': 'ip_h'}).get('value')
            lg_h = soup.find('input', {'name': 'lg_h'}).get('value')
            return True
        except:
            return False

    def _open_main_page(self):
        self._log('run _open_main_page')
        time.sleep(3)
        r = self._get('https://vk.com/')
        if self._needs_login(r):
            if self._needs_change_language(r):
                self._change_language(r)
                r = self._get('https://vk.com/')
            if not self._login(r):
                return False
            time.sleep(3)
            r = self._get('https://vk.com/')

        if r.status_code == 200:
            try:
                self.vk_id = re.search(r',\n  id: ([0-9]+)', r.text, re.M).group(1)
                return True
            except AttributeError:
                pass

        return False

    def _parse_int_from_human_number(self, number):
        if number == '':
            return 0
        result = float(re.search(r'[\d\.]+', number).group())
        if 'K' in number:
            result = result * 1000
        if 'M' in number:
            result = result * 1000000
        if 'B' in number:
            result = result * 1000000000
        return result

    def _parse_wall_post(self, post):
        result = {
            'rating': 0
        }
        try:
            result['id'] = post.get('id')
            result['original_id'] = post.get('data-copy')
            result['view_hash'] = post.get('post_view_hash'),
            result['author_name'] = post.select_one('.post_author > a.author').getText()
            result['author_link'] = post.select_one('.post_author > a.author').get('href')
            try:
                result['copy_author_name'] = post.select_one('.copy_post_author > a.copy_author').getText()
                result['copy_author_link'] = post.select_one('.copy_post_author > a.copy_author').get('href')
            except Exception:
                result['copy_author_name'] = None
                result['copy_author_link'] = None
            result['date'] = self._parse_wall_post_date(post)
            result['likes'] = post.select_one('.post_like_count._count').getText()
            result['reposts'] = post.select_one('.post_share_count._count').getText()
            result['views'] = post.select_one('.post_views_count._count').getText()

            result['likes'] = self._parse_int_from_human_number(result['likes'])
            result['reposts'] = self._parse_int_from_human_number(result['reposts'])
            result['views'] = self._parse_int_from_human_number(result['views'])

            result['rating'] = (result['likes'] + result['reposts']) / result['views'] * 100
        except Exception as e:
            pass
        return result

    def _parse_wall_post_date(self, post):
        try:
            post_date = post.select_one('.post_header .post_date').getText()
            if "год" in post_date or "года" in post_date or "лет" in post_date:
                return 0

            if "назад" in post_date:
                return time.time()

            post_date = post_date.split(' в ')
            post_date = {
                'date': post_date[0],
                'time': post_date[1]
            }
            if post_date['date'] == 'сегодня':
                post_date['date'] = datetime.datetime.now().strftime("%d-%m-%Y")
            elif post_date['date'] == 'вчера':
                post_date['date'] = datetime.datetime.now() - datetime.timedelta(days=1)
                post_date['date'] = post_date['date'].strftime("%d-%m-%Y")
            else:
                post_date['date'] = post_date['date'].split(' ')
                post_date['date'][1] = months[post_date['date'][1]]
                if len(post_date['date']) == 2:
                    post_date['date'].append(str(datetime.datetime.now().year))
                post_date['date'] = '-'.join(str(v) for v in post_date['date'])

            post_date_string = post_date['date'] + ' ' + post_date['time']
            post_date = datetime.datetime.strptime(post_date_string, '%d-%m-%Y %H:%M')
            return post_date.timestamp()
        except Exception as e:
            self._log('exception in _parse_wall_post_date. post_date=' + str(post_date) + ' ' + str(e).encode().decode("utf-8"))
            return 0

    def _post(self, *args, **kwargs):
        try:
            result = self.get_session().post(*args, **kwargs)
        except BrokenPipeError:
            self._log('BrokenPipeError, reinit session')
            self._init_session()
            result = self.get_session().post(*args, **kwargs)
        return result

    def _repost_post(self, post):
        post_id = 'wall'+post['id'].replace('post', '')
        params = {
            'act': 'publish_box',
            'al': 1,
            'object': post_id
        }
        time.sleep(3)
        r = self._post('https://vk.com/like.php', data=params)

        try:
            share_hash = re.search('shHash: \'([^\']+)\'', r.text).group(1)
        except AttributeError:
            return False

        params = {
            'act': 'a_do_publish',
            'al': '1',
            'from': 'box',
            'hash': share_hash,
            'list': '',
            'object': post_id,
            'to': 0
        }
        time.sleep(3)
        r = self._post('https://vk.com/like.php', data=params)

        if re.match('(.*)Запись отправлена', r.text):
            self._save_session()
            self._log('a post ' + str(post['id']) + ' reposted successfully')
            return True

        return False

    def _save_session(self):
        os.makedirs(os.path.dirname('tmp/vk_cookies.out'), exist_ok=True)
        with open('tmp/vk_cookies.out', 'wb+') as f:
            f.truncate()
            cookies = requests.utils.dict_from_cookiejar(self.get_session().cookies)
            pickle.dump(cookies, f)
        return True

    def _search_friend(self):
        time.sleep(3)
        r = self._get('https://vk.com/friends?act=find')
        city = self._cities.get_rand_city()
        status = random.choice([1, 5, 6])

        def recursive_search_friends(offset=0):
            # 'c[sex]': 2,
            params = {
                'al': '1',
                'c[age_from]': 18,
                'c[age_to]': 45,
                'c[city]': city,
                'c[country]': 1,
                'c[online]': 1,
                'c[photo]': 1,
                'c[section]': 'people',
                'c[status]': status,
                'change': 1,
                'search_loc': 'friends?act=find',
            }
            if offset > 0:
                params['al_ad'] = 0
                params['offset'] = offset

            time.sleep(3)
            r = self._post('https://vk.com/al_search.php', data=params)

            try:
                result = re.search('"has_more":true', r.text).group(0)
                new_offset = re.search('"offset":([0-9]+)', r.text).group(1)
                new_offset = int(new_offset)
                has_more = True
            except AttributeError:
                new_offset = None
                has_more = False

            buttons = re.findall('<button id="search_sub([0-9]+)"([^>]*)this, ([0-9]+), \'([^>]*)\', true([^>]*)>Добавить в друзья</button>', r.text)
            ids = []
            for friend_id, trash, same_id, friend_hash, button_end in buttons:
                if not re.match('(.*)display: none;(.*)', button_end):
                    ids.append((friend_id, friend_hash))

            if not len(ids) and has_more and new_offset and new_offset > offset:
                ids = recursive_search_friends(new_offset)
            return ids

        people_ids = recursive_search_friends()

        if not len(people_ids):
            return False, False
        if len(people_ids) > 1:
            friend_id, friend_hash = people_ids[1]
        else:
            friend_id, friend_hash = people_ids[0]

        return friend_id, friend_hash

    def _solve_captcha(self, captcha_key):
        result = self._solve_antigate_captcha(captcha_key)
        if not result:
            result = self._solve_rucaptcha_captcha(captcha_key)
        return result

    def _solve_antigate_captcha(self, captcha_key):
        self._log('Resolving captcha in Antigate')
        task = NoCaptchaTaskProxyless.NoCaptchaTaskProxyless(anticaptcha_key=self.antigate_key)
        result = task.captcha_handler(websiteURL='https://vk.com', websiteKey=captcha_key)
        if result['errorId'] == 0 and 'solution' in result:
            solution = result['solution']
            if 'gRecaptchaResponse' in solution:
                return solution['gRecaptchaResponse']
        return False

    def _solve_rucaptcha_captcha(self, captcha_key):
        self._log('Resolving captcha in RuCaptcha')
        url = 'http://rucaptcha.com/in.php?key=' + self.rucaptcha_key + '&method=userrecaptcha&googlekey=' + captcha_key + '&pageurl=https://vk.com'
        r = requests.get(url)
        if r.status_code != 200:
            self._log('Rucaptcha returns error ' + str(r.status_code) + ' for url: ' + url)
            return False

        captcha_id = r.text[3:]

        while True:
            time.sleep(10)
            url = 'http://rucaptcha.com/res.php?key=' + self.rucaptcha_key + '&action=get&id=' + captcha_id
            r = requests.get(url)
            if r.status_code != 200:
                self._log('Rucaptcha returns error ' + str(r.status_code) + ' for url: ' + url)
                return False

            if r.text != 'CAPCHA_NOT_READY':
                if r.text[:3] != 'OK|':
                    return False
                return r.text[3:]


def cycle_bot(sc, bot):
    print("Cycling bot...")
    action = False

    now = datetime.datetime.now()
    if now.hour > 3:
        if not action:
            if bot.check_action_timestamp(bot.ACTION_REPOST_RANDOM):
                action = bot.repost_random_post()
                if action:
                    bot.update_action_timestamp(bot.ACTION_REPOST_RANDOM)
        if not action:
            if bot.check_action_timestamp(bot.ACTION_REPOST_OUR):
                action = bot.repost_our_post()
                if action:
                    bot.update_action_timestamp(bot.ACTION_REPOST_OUR)
        if not action:
            if bot.check_action_timestamp(bot.ACTION_ADD_FRIEND):
                action = bot.add_friend()
                bot.update_action_timestamp(bot.ACTION_ADD_FRIEND)

        if not action:
            if bot.check_action_timestamp(bot.ACTION_CHECK_FRIENDS):
                action = bot.check_friends()
                bot.update_action_timestamp(bot.ACTION_CHECK_FRIENDS)

        if not action and now.hour == 11:
            if bot.check_action_timestamp(bot.ACTION_SEND_STAT):
                action = bot.send_stat()
                bot.update_action_timestamp(bot.ACTION_SEND_STAT)

        if not action:
            if bot.check_action_timestamp(bot.ACTION_VISIT_GROUP):
                action = bot.visit_group()
                bot.update_action_timestamp(bot.ACTION_VISIT_GROUP)

        if not action:
            if bot.check_action_timestamp(bot.ACTION_ONLINE):
                bot.get_online()
                bot.update_action_timestamp(bot.ACTION_ONLINE)

    sc.enter(60, 1, cycle_bot, (sc, bot))


admin_vk_id = settings.admin_vk_id
username = settings.username
password = settings.password
antigate_key = settings.antigate_key
rucaptcha_key = settings.rucaptcha_key
vk_my_group = settings.vk_my_group

logger = Logger()


def run_bot():
    try:
        if len(sys.argv) < 2 or sys.argv[1] != 'debug':
            time.sleep(random.randint(1, 301))
        skynet_bot = SkynetBot(admin_vk_id=admin_vk_id, username=username, password=password, logger=logger,
                               antigate_key=antigate_key, rucaptcha_key=rucaptcha_key,
                               vk_my_group=vk_my_group)
        scheduler = sched.scheduler(time.time, time.sleep)
        scheduler.enter(5, 1, cycle_bot, (scheduler, skynet_bot))
        scheduler.run()
    except Exception as e:
        logger.crash_log(e)
        run_bot()


run_bot()
