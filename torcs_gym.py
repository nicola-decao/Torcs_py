import subprocess

import numpy as np
from gym import spaces
from gym.core import Env
import os
import socket
import sys
import time
from xml.etree import ElementTree as etree

TRACK_LIST = {'aalborg': 'road',
              'alpine-1': 'road',
              'alpine-2': 'road',
              'brondehach': 'road',
              'corkscrew': 'road',
              'eroad': 'road',
              'e-track-1': 'road',
              'e-track-2': 'road',
              'e-track-3': 'road',
              'e-track-4': 'road',
              'e-track-6': 'road',
              'forza': 'road',
              'g-track-1': 'road',
              'g-track-2': 'road',
              'g-track-3': 'road',
              'ole-road-1': 'road',
              'ruudskogen': 'road',
              'spring': 'road',
              'street-1': 'road',
              'wheel-1': 'road',
              'wheel-2': 'road',
              'a-speedway': 'oval',
              'b-speedway': 'oval',
              'c-speedway': 'oval',
              'd-speedway': 'oval',
              'e-speedway': 'oval',
              'e-track-5': 'oval',
              'f-speedway': 'oval',
              'g-speedway': 'oval',
              'michigan': 'oval',
              'dirt-1': 'dirt',
              'dirt-2': 'dirt',
              'dirt-3': 'dirt',
              'dirt-4': 'dirt',
              'dirt-5': 'dirt',
              'dirt-6': 'dirt',
              'mixed-1': 'dirt',
              'mixed-2': 'dirt'}


class TorcsEnv(Env):
    def __init__(self, host='localhost', port=3001, sid='SCR', track='g-track-1', gui=True, timeout=10000, reward=None):
        # TODO fix gui=False

        self.gui = gui
        self.server = self.Server(track, TRACK_LIST[track], gui, timeout=timeout)
        self.client = self.Client(self.server, host, port, sid)
        self.__terminal_judge_start = 250
        self.__termination_limit_progress = 20
        self.__gearUp = (9000, 8500, 8500, 8000, 8000, 0)
        self.__gearDown = (0, 3500, 4000, 4000, 4500, 4500)
        self.__gear = 0
        self.__last_rmp = 0
        self.__time_stop = 0

        if reward:
            self.__reward = reward
        else:
            self.__reward = self.__default_reward

        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(2,))
        self.observation_space = spaces.Box(low=0, high=0, shape=(29,))

    def _reset(self):
        if self.gui:
            self.client.send_restart_request()
        else:
            self.server.restart()
        self.client.restart()
        self.__gear = 0
        self.__last_rmp = 0
        self.__time_stop = 0
        time.sleep(0.1)
        return self.__encode_state_data(self.client.step())

    @staticmethod
    def __default_reward(sensors):
        if np.abs(sensors['trackPos']) > 0.99:
            reward = -200
        else:
            reward = sensors['speedX'] * (
                np.cos(sensors['angle'])
                - np.abs(np.sin(sensors['angle']))
                - np.abs(sensors['trackPos']))
        return reward

    def __check_done(self, sensors):
        if sensors['speedX'] < self.__termination_limit_progress:
            self.__time_stop += 1
        else:
            self.__time_stop = 0

        return self.__time_stop > self.__terminal_judge_start or np.abs(sensors['trackPos']) > 0.99

    def _step(self, action):
        a = self.__decode_action_data(action)

        change_gear = False
        if self.__gear < 1:
            self.__gear = 1
        elif self.__gear < 6 and self.__last_rmp >= self.__gearUp[self.__gear - 1]:
            self.__gear += 1
            change_gear = True
        else:
            if self.__gear > 1 and self.__last_rmp <= self.__gearDown[self.__gear - 1]:
                self.__gear -= 1
                change_gear = True

        a['gear'] = self.__gear

        sensors = self.client.step(a)

        if change_gear:
            self.__last_rmp = 5000
        else:
            self.__last_rmp = sensors['rpm']

        observation = self.__encode_state_data(sensors)
        reward = self.__reward(sensors)
        done = self.__check_done(sensors)
        return observation, reward, done, {}

    @staticmethod
    def __decode_action_data(actions_vec):
        actions_dic = TorcsEnv.Client.get_empty_actions()
        if actions_vec[0] >= 1:
            actions_vec[0] = 0.9999
        elif actions_vec[0] <= -1:
            actions_vec[0] = -0.9999
        steering = np.tanh(np.arctanh(actions_vec[0])/2)
        actions_dic['steer'] = steering

        if actions_vec[1] >= 0:
            actions_dic['accel'] = actions_vec[1]
        else:
            actions_dic['brake'] = -actions_vec[1]

        return actions_dic

    def __encode_state_data(self, sensors):
        state = np.empty(self.observation_space.shape[0])
        state[0] = sensors['angle'] / np.pi
        state[1:20] = np.array(sensors['track']) / 200.0
        state[20] = sensors['trackPos'] / 1.0
        state[21] = sensors['speedX'] / 300.0
        state[22] = sensors['speedY'] / 300.0
        state[23] = sensors['speedZ'] / 300.0
        state[24:28] = np.array(sensors['wheelSpinVel']) / 100.0
        state[28] = sensors['rpm'] / 10000.0
        return state

    class Server:

        def __init__(self, track, track_type, gui, timeout=10000):
            self.__gui = gui
            self.__quickrace_xml_path = os.path.expanduser('~') + '/.torcs/config/raceman/quickrace.xml'
            self.__create_race_xml(track, track_type)
            self.__timeout = timeout
            self.__init_server()


        @staticmethod
        def __cmd_exists(cmd):
            return subprocess.call("type " + cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0

        def __init_server(self):
            os.system('pkill torcs')
            time.sleep(0.1)
            if self.__gui:
                if self.__cmd_exists('optirun'):
                    os.system('optirun torcs -nofuel -nodamage -nolaptime -t {} >/dev/null &'.format(self.__timeout))
                else:
                    os.system('torcs -nofuel -nodamage -nolaptime -t {} >/dev/null &'.format(self.__timeout))
                time.sleep(2)
                os.system('sh autostart.sh')
            else:
                os.system('torcs -nofuel nodamage -nolaptime -r ' + self.__quickrace_xml_path + ' >/dev/null &')
            #print('Server created!')
            time.sleep(0.1)

        def restart(self):
            #print('Restarting __server...')
            os.system('pkill torcs')
            time.sleep(0.2)
            self.__init_server()

        def __create_race_xml(self, track, track_type):
            root = etree.parse(self.__quickrace_xml_path)
            track_name = root.find('section[@name="Tracks"]/section[@name="1"]/attstr[@name="name"]')
            track_name.set('val', track)
            track_type_tree = root.find('section[@name="Tracks"]/section[@name="1"]/attstr[@name="category"]')
            track_type_tree.set('val', track_type)
            laps = root.find('section[@name="Quick Race"]/attnum[@name="laps"]')
            laps.set('val', '1000')
            track_type_tree.set('val', track_type)
            root.write(self.__quickrace_xml_path)

    class Client:
        def __init__(self, server, host, port, sid):
            self.__server = server
            self.__host = host
            self.__port = port
            self.__sid = sid
            self.__data_size = 2 ** 17
            self.__socket = self.__create_socket()
            self.__connect_to_server()

        @staticmethod
        def get_empty_actions():
            return {'steer': 0, 'accel': 0, 'gear': 1, 'brake': 0, 'clutch': 0, 'meta': 0,
                    'focus': [-90, -45, 0, 45, 90]}

        def restart(self):
            self.__socket = self.__create_socket()
            self.__connect_to_server()

        def send_restart_request(self):
            actions = self.get_empty_actions()
            actions['meta'] = True
            message = self.__encode_actions(actions)
            self.__send_message(message)

        def __send_message(self, message):
            try:
                self.__socket.sendto(message.encode(), (self.__host, self.__port))
            except socket.error as emsg:
                print(u"Error sending to __server: %s Message %s" % (emsg[1], str(emsg[0])))
                sys.exit(-1)

        @staticmethod
        def __create_socket():
            try:
                so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            except socket.error:
                print('Error: Could not create __socket...')
                sys.exit(-1)
            so.settimeout(1)
            return so

        def __connect_to_server(self):
            tries = 3
            while True:
                sensor_angles = "-45 -19 -12 -7 -4 -2.5 -1.7 -1 -.5 0 .5 1 1.7 2.5 4 7 12 19 45"
                initmsg = '%s(init %s)' % (self.__sid, sensor_angles)

                try:
                    self.__socket.sendto(initmsg.encode(), (self.__host, self.__port))
                except socket.error:
                    sys.exit(-1)
                sockdata = str()

                try:
                    sockdata, address = self.__socket.recvfrom(self.__data_size)
                    sockdata = sockdata.decode('utf-8')
                except socket.error:
                    #print("Waiting for __server on __port " + str(self.__port))
                    tries -= 1
                    if tries == 0:
                        #print("Server didn't answer, sending restart signal")
                        self.__server.restart()

                identify = '***identified***'
                if identify in sockdata:
                    #print("Client connected on __port " + str(self.__port))
                    break

        @staticmethod
        def __encode_actions(actions):
            out = str()
            for k in actions:
                out += '(' + k + ' '
                v = actions[k]
                if not type(v) is list:
                    out += '%.3f' % v
                else:
                    out += ' '.join([str(x) for x in v])
                out += ')'
            return out

        @staticmethod
        def __limit_action(v, lo, hi):
            if v < lo:
                return lo
            elif v > hi:
                return hi
            else:
                return v

        def __limit_actions(self, actions):
            actions['steer'] = self.__limit_action(actions['steer'], -1, 1)
            actions['brake'] = self.__limit_action(actions['brake'], 0, 1)
            actions['accel'] = self.__limit_action(actions['accel'], 0, 1)
            actions['clutch'] = self.__limit_action(actions['clutch'], 0, 1)
            if actions['gear'] not in [-1, 0, 1, 2, 3, 4, 5, 6]:
                actions['gear'] = 0
            if actions['meta'] not in [0, 1]:
                actions['meta'] = 0
            if type(actions['focus']) is not list or min(actions['focus']) < -180 or max(
                    actions['focus']) > 180:
                actions['focus'] = 0

        def step(self, action=None):
            if action is None:
                action = self.get_empty_actions()

            if not self.__socket:
                print('Client __socket problem!')
                return
            self.__limit_actions(action)
            message = self.__encode_actions(action)
            self.__send_message(message)

            return self.__get_server_input()

        def __parse_server_string(self, server_string):
            track_data = {}
            server_string = server_string.strip()[:-1]
            server_string_list = server_string.strip().lstrip('(').rstrip(')').split(')(')
            for i in server_string_list:
                w = i.split(' ')
                track_data[w[0]] = self.__destringify(w[1:])
            return track_data

        def __destringify(self, string):
            if not string:
                return string
            if type(string) is str:
                try:
                    return float(string)
                except ValueError:
                    print("Could not find a value in %s" % string)
                    return string
            elif type(string) is list:
                if len(string) < 2:
                    return self.__destringify(string[0])
                else:
                    return [self.__destringify(i) for i in string]

        def __get_server_input(self):
            sockdata = str()
            while True:
                try:
                    sockdata, address = self.__socket.recvfrom(self.__data_size)
                    sockdata = sockdata.decode('utf-8')
                except socket.error:
                    print('', end='')
                if sockdata:
                    return self.__parse_server_string(sockdata)
