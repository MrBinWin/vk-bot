import os
import traceback
from time import gmtime, strftime


class Logger:

    def log(self, msg):
        try:
            os.makedirs(os.path.dirname('tmp/bot_log.out'), exist_ok=True)
            now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
            msg = now+': '+msg.encode().decode("utf-8")+'\r\n'
            print(msg)
            with open('tmp/bot_log.out', 'a') as f:
                f.write(msg)
        except BrokenPipeError as e:
            with open('broken_pipe_log.out', 'a') as f:
                f.write(traceback.format_exc())

    def crash_log(self, e):
        try:
            os.makedirs(os.path.dirname('tmp/crash_log.out'), exist_ok=True)
            now = strftime("%Y-%m-%d %H:%M:%S", gmtime())
            traceback_str = traceback.format_exc()
            msg = now+': '+str(e).encode().decode("utf-8")+'\r\n'+traceback_str+'\r\n'
            print(msg)
            with open('crash_log.out', 'a') as f:
                f.write(msg)
        except BrokenPipeError as e:
            with open('broken_pipe_log.out', 'a') as f:
                f.write(traceback.format_exc())
