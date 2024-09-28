# phase3.py
import logging
import os
import subprocess as sp
import sys
import time

from v2s.phase import AbstractPhase
from v2s.phase3.script_generation.action_to_event_conversion import \
    Action2EventConverter
from v2s.util.event import ActionType, GUIAction
from v2s.util.general import JSONFileUtils, RecordThread, Translator
from v2s.util.screen import ScreenTap


class Phase3V2S(AbstractPhase):
    """
    Phase 3 of V2S pipeline. Takes care of translating GUIActions into replayable
    events.

    Attributes
    ----------
    config : dict
        configuration with video/replay information
    adb : string
        path to Android Debugging Bridge
    actions : list of GUIActions
        actions from Phase 2
    action2event_converter : Action2EventConverter
        translates into reran events
    events : list of Events
        events converted from Phase2
    raw_commands : list of strings
        string of event commands that can be fed directly to the device
    

    Methods
    --------
    execute()
        Execute the action translation.
    init_device_for_replay(emulator)
        Initialize device for replay by getting first name in the list of devices.
    read_actions_from_json(action_path, vid_file)
        Reads actions from json file from Phase 2.
    output_to_file(data, file_path)
        Outputs data to file.
    get_actions()
        Returns dict of GUIActions.
    set_actions(actions)
        Changes detected actions to specified value.
    get_events()
        Returns dict of converted events.
    set_events(events)
        Changes events to specified value.
    get_video_path()
        Returns video path.
    set_video_path(path)
        Changes video path to specified value.
    set_raw_commands(commands)
        Changes raw commands to specified value.
    get_raw_commands()
        Returns raw commands.
    """

    def __init__(self, adb_path, config):
        """
        Parameters
        ----------
        adb_path : string
            path to adb executable
        config : dict
            configuration with video/device information
        """
        self.config = config
        self.adb = adb_path
        self.events = []
        # will have to be set later
        self.actions = []
        self.action2event_converter = Action2EventConverter(None, self.adb)
        self.raw_commands = []

    def execute(self):
        """
        Execute the action translation.
        """
        # get the name of device for replay
        # if more than one connected, initializes with the first one listed
        # only needs to occur once because all replays will occur on same device
        cur_path = self.config["video_path"]
        device_model = self.config["device_model"]
        app_name = self.config["app_name"]
        app_data = JSONFileUtils.read_data_from_json(os.path.join(sys.prefix, 'v2s', 
                                                        'app_config.json'))
        app_pkg = app_data["app_pkgs"][app_name]
        app_apk = os.path.join(sys.prefix, app_data["app_apks"][app_name])
        # get the device architecture
        arch = self.config["arch"]
        emulator = self.config["emulator"]=="True"

        # init device name
        device_name = self.init_device_for_replay(arch)

        # set up the path to directory where all information is held
        video_dir, video_file = os.path.split(cur_path)
        video_name, video_extension = os.path.splitext(video_file)
        cur_dir_path = os.path.join(video_dir, video_name)

        logging.basicConfig(filename=os.path.join(cur_dir_path, 'v2s.log'), filemode='w', level=logging.INFO)
        
        # 1) Event Conversion
        # get actions from phase 2
        action_path = os.path.join(cur_dir_path, "detected_actions.json")
        self.read_actions_from_json(action_path, video_file)
        self.action2event_converter.set_actions(self.actions)
        
        # give converter the correct configuration file for device
        device_path = os.path.join(sys.prefix, 'v2s', 'device_config.json')
        device_config = JSONFileUtils.read_data_from_json(device_path)[device_model]
        self.action2event_converter.set_config(device_config)
        # execute the converter on the actions for the specific video file
        self.action2event_converter.execute()
        # extract the events
        self.events = self.action2event_converter.get_event_list()
        # output phase 3 raw commands to a file
        log_path = os.path.join(cur_dir_path, "send_events.log")
        self.raw_commands = self.action2event_converter.extract_raw_from_events()
        self.output_to_file(self.raw_commands, log_path)
        reran_out_path = os.path.join(cur_dir_path, "events_4_reran.log")
        # translate to reran-readable file
        reran_data = Translator.translate(log_path)
        self.output_to_file(reran_data, reran_out_path)

        # 2) Replay
        # push the correct files to the device
        # first the reran script
        if arch.lower() == "x86":
            reran_path = os.path.join(sys.prefix, 'v2s', 'phase3', 'reran', 'replay-i686')
        elif arch.lower() == "arm":
            reran_path = os.path.join(sys.prefix, 'v2s', 'phase3', 'reran', 'replay-arm')
        reran_remote_path = '/data/local/tmp/replay'
        push_reran = [self.adb, '-s', device_name, 'push', reran_path, 
                reran_remote_path]
        push1 = sp.check_output(push_reran, shell=False, stderr=sp.STDOUT)
        push1 = push1.decode('utf-8')
        logging.info(push1)
        
        # then the log file with the replicated events
        log_remote_path = '/data/local/tmp/output'
        push_events = [self.adb, '-s', device_name, 'push', reran_out_path, 
                log_remote_path]
        push2 = sp.check_output(push_events, shell=False, stderr=sp.STDOUT)
        push2 = push2.decode('utf-8')
        logging.info(push2)

        # make sure that the correct app is installed
        install = [self.adb, '-s', device_name, 'install', app_apk]
        inst = sp.Popen(install, shell=False, stdout=sp.PIPE, stderr=sp.PIPE)
        inst.wait()
        inst.terminate()
        for line in inst.stdout:
            logging.info(line.decode('utf-8'))
        for line in inst.stderr:
            logging.info(line.decode('utf-8'))

        # start the screen record on a new thread
        # configure the size of the video so that screenrecording is possible
        width = device_config['width']
        height = device_config['height']
        size = str(width) + 'x' + str(height)
        logging.info("Starting screenrecording.")
        replay_path = '/sdcard/' + video_name + '_replay.mp4'
        record_thread = RecordThread(self.adb, replay_path, device_name, size)
        record_thread.start()
        replay_path = record_thread.get_replay_path()

        # launch the correct application
        launch = [self.adb, '-s', device_name, 'shell', 'monkey', '-p',
                app_pkg, '-c', 'android.intent.category.LAUNCHER', '1']
        app = sp.Popen(launch, shell=False, stdout=sp.PIPE, stderr=sp.PIPE)
        app.wait()
        app.terminate()
        for line in app.stdout:
            logging.info(line.decode('utf-8'))
        for line in app.stderr:
            logging.info(line.decode('utf-8'))
        # make sure that the app has opened
        time.sleep(10)

        # execute the sendevents
        root = [self.adb, '-s', device_name, 'root']
        root = sp.check_output(root, shell=False, stderr=sp.STDOUT)
        root = root.decode('utf-8')
        logging.info(root)
        
        # updates permissions so that anyone can execute
        execute_chmod = [self.adb, '-s', device_name, 'shell', 'chmod', 
                    '755', reran_remote_path]
        execute_events = [self.adb, '-s', device_name, 'shell',  
                    reran_remote_path, log_remote_path]
        chmod = sp.check_output(execute_chmod, shell=False, stderr=sp.STDOUT)
        events = sp.check_output(execute_events, shell=False, stderr=sp.STDOUT)
        chmod = chmod.decode('utf-8')
        events = events.decode('utf-8')
        logging.info(chmod)
        logging.info(events)
        
        time.sleep(5)

        # stop the screen recording
        logging.info("Terminating recording.")
        kill = [self.adb, '-s', device_name, 'shell', 'kill', '-SIGINT',
                '`pgrep -f screenrecord`']
        kill = sp.Popen(kill, shell=False, stdout=sp.PIPE, stderr=sp.PIPE)
        kill.wait()
        kill.terminate()
        for line in kill.stdout:
            logging.info(line.decode('utf-8'))
        for line in kill.stderr:
            logging.info(line.decode('utf-8'))
        
        record_thread.join()
        time.sleep(3)

        # pull the recorded video to local device
        video_out_path = os.path.join(cur_dir_path, video_name + '_replay.mp4')
        pull = [self.adb, '-s', device_name, 'pull', replay_path, video_out_path]
        pull = sp.check_output(pull, shell=False, stderr=sp.STDOUT)
        pull = pull.decode('utf-8')
        logging.info(pull)
        logging.info("Video pulled.")
    
    def init_device_for_replay(self, emulator):
        """
        Initialize device for replay by getting first name in the list of devices.

        Parameters
        ----------
        emulator : bool
            depicts whether replay will occur on an emulator

        Returns
        -------
        device_name : string
            name of device for replay
        """
        command = [self.adb, 'devices']
        # get the output and decode it to a string
        devices = (sp.check_output(command, shell=False).rstrip()).decode("utf-8")
        # process devices
        devices = devices.split('\n')
        # if only title remaining, then no devices are connected
        if len(devices) == 1:
            sys.exit("Error: No device connected. Please begin an emulator session or connect device.")
        # chop off title of output
        devices = devices[1:]
        # marks whether the proper device was identified
        device_found = False
        if emulator:
            for line in devices:
                if "emulator" in line.lower():
                    device_name = line.split()[0]
                    device_found = True
                    break
            if not device_found:
                sys.exit("Error: Emulator specified but not found to replay scenario.")
        else:
            for line in devices:
                if "emulator" not in line.lower():
                    device_name = line.split()[0]
                    device_found = True
                    break
            if not device_found:
                sys.exit("Error: Physical device specified but not found to replay scenario.")
        return device_name

    def read_actions_from_json(self, action_path, vid_file):
        """
        Reads actions from json file from Phase 2.

        Parameters
        ----------
        action_path : string
            path to action json file
        vid_file : string
            video file name for dictionary key
        """
        # returns JSON object as  
        # a dictionary 
        data = JSONFileUtils.read_data_from_json(action_path)
        
        # # list of frames that will be appended to as they are loaded
        actions = []
        for action_dict in data:
            frames = action_dict["frames"]
            taps = action_dict["taps"]
            tp = action_dict["act_type"]
            if tp == "CLICK":
                tp = ActionType.CLICK
            elif tp == "LONG_CLICK":
                tp = ActionType.LONG_CLICK
            elif tp == "SWIPE":
                tp = ActionType.SWIPE
            
            # load tap information
            tap_list = []
            for tap in taps:
                # extract tap information
                x = tap["x"]
                y = tap["y"]
                touch_confidence = tap["confidence"]
                opacity_confidence = tap["confidenceOpacity"]
                # create new tap
                new_tap = ScreenTap(x, y, touch_confidence)
                new_tap.set_opacity_confidence(opacity_confidence)
                tap_list.append(new_tap)
            # create new GUIAction object
            action = GUIAction(tap_list, frames, tp)
            actions.append(action)

        self.actions = actions
    
    def output_to_file(self, data, file_path):
        """
        Outputs data to file.

        Parameters
        ----------
        data : iterable data
            data to write to a file
        file_path : string
            location where raw commands will be output
        """  
        
        # write commands to the file
        with open(file_path, 'w') as f:
            for i in data:
                f.write(i + "\n")

    def get_actions(self):
        """
        Returns dict of GUIActions.
        """
        return self.actions
        
    def set_actions(self, actions):
        """
        Changes detected actions to specified value.
        """
        self.actions = actions

    def get_events(self):
        """
        Returns dict of converted events.

        Returns
        -------
        events : dict
            events converted from Phase2
        """
        return self.events

    def set_events(self, events):
        """
        Changes events to specified value.

        Parameters
        ----------
        events : dict
            new events
        """
        self.events = events
    
    def get_video_path(self):
        """
        Returns video path.

        Returns
        -------
        video_path : string
            path to video
        """
        return self.video_path

    def set_video_path(self, path):
        """
        Changes video path to specified value.

        Parameters
        ----------
        path : string
            new video path
        """
        self.video_path = path

    def set_raw_commands(self, commands):
        """
        Changes raw commands to specified value.

        Returns
        -------
        raw_commands : list of strings
            path to video
        """
        self.raw_commands = commands

    def get_raw_commands(self):
        """
        Returns raw commands.
        """
        return self.raw_commands
