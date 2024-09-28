# action_to_event_conversion.py
import json
import logging
import os
import subprocess as sp
import sys
from abc import ABC, abstractmethod

from v2s.util.constants import (DEF_PRESSURE, DELAY_OFFSET, FRAMES_CONV_FACTOR,
                            WAIT_PER_COMMAND)
from v2s.util.event import ActionType, Event, GUIAction
from v2s.util.spatial import Coords


class AbstractAction2EventConverter(ABC):
    """
    Converts GUIActions to raw event commands that can be replayed on a device.

    Attributes
    ----------
    raw_commands : list of strings
        raw commands that can be read by a device to replay scenario

    Methods
    -------
    execute()
        Executes conversion between action and raw commands.
    get_raw_commands()
        Returns raw commands.
    set_raw_commands(commands)
        Changes raw commands to specified value.
    """

    @abstractmethod
    def __init__(self):
        self.raw_commands = []

    @abstractmethod
    def execute(self):
        """
        Executes conversion between action and raw commands.
        """
        pass

    def get_raw_commands(self):
        """
        Returns raw commands.

        Returns
        -------
        raw_commands : list of stringg
            raw commands for actions
        """
        return self.raw_commands

    def set_raw_commands(self, commands):
        """
        Changes raw commands to specified value.

        Parameters
        ----------
        commands : list of string
            new raw commands
        """
        self.raw_commands = commands

class Action2EventConverter(AbstractAction2EventConverter):
    """
    Action to Event Converter for V2S. Takes actions that were detected in 
    Phase 2 and outputs them to events that have raw commands that are 
    replayable by a device.

    Attributes
    ----------
    actions : list of GUIActions
        actions detected from Phase 2
    adb : string
        path to Android Debugging Bridge
    event_list : list of Events
        list of Events that is device independent
    raw_commands : list of strings
        commands that are specific to a device and are replayable
    input_device : string
        device that can be manipulated and is referenced in 'adb shell getevent'
    send_x_comm : string
        base command for x coordinate of tap
    send_y_comm : string
        base command for y coordinate of tap
    max_x : float
        maximum x value used for converting display coordinates into touch
        coordinates
    max_y : float
        maximum y value used for converting display coordinates into touch
        coordinates
    display_width : float
        width of screen on device used for converting display coordinates into 
        touch coordinates
    display_height : float
        height of screen on device used for converting display coordinates into
        touch coordinates
    config : dict
        device configuration with all of device-specific codes listed

    Methods
    -------
    execute() 
        Executes Phase 3 of V2S. Generates a replayable script on a device.
    init_input_device()
        Initializes the input device with all of its parameters.
    convert_GUIAction_to_send_event():
        Takes care of converting the GUIActions from Phase 2 into Events that
        have raw commands associated with them.
    add_fake_tap()
        Adds a fake tap as the first event to ensure that all events are captured
        in replay.
    get_actions():
        Returns actions detected from Phase 2.
    set_actions(acts):
        Changes actions to specified value.
    extract_raw_from_events():
        Extracts the raw commands from the events.
    get_event_list()
        Returns event list.
    set_event_list(events)
        Changes event list to specified value.
    get_input_device()
        Returns input device.
    set_input_device(dev)
        Changes input device to specified value.
    get_send_x_comm()
        Returns send x command.
    set_send_x_comm(command)
        Changes send x command to specified value.
    get_send_y_comm()
        Returns send y command.
    set_send_y_comm(command)
        Changes send y command to specified value.
    get_max_x()
        Returns max x.
    set_max_x(max)
        Changes max x to specified value.
    get_max_y()
        Returns max y.
    set_max_y(max)
        Changes max y to specified value.
    get_display_width()
        Return display width.
    set_display_width(width)
        Changes display width to specified value.
    get_display_height()
        Return display height.
    set_display_height(height)
        Changes display height to specified value.
    get_config()
        Returns device configuration.
    set_config(config)
        Changes device configuration to specified value.
    """

    def __init__(self, actions, adb, config=None):
        """
        Parameters
        ----------
        actions : list of GUIActions
            actions detected in Phase 2
        adb : string
            path to Android Debugging Bridge
        config : dict
            device configuration
        """
        super().__init__()
        self.actions = actions
        self.adb = adb
        self.event_list = []
        self.config = config

    def execute(self):
        """
        Executes Phase 3 of V2S. Generates a replayable script on a device.
        """
        self.init_input_device()
        self.convert_GUIAction_to_send_event()
    
    def init_input_device(self):
        """
        Initializes the input device with all of its parameters. Only one device
        should be connected.
        """
        logging.info("Initializing device.")
        # device measurements
        self.max_x = self.config["max_x"]
        self.max_y = self.config["max_y"]
        self.display_width = self.config["width"]
        self.display_height = self.config["height"]
        # set the device to be used for sendevents
        self.input_device = str(self.config["device"]) + ": "
        # commands for specifying location of a tap, swipe, etc.
        self.send_x_cmd = (self.input_device + str(self.config["EV_ABS"]) + " " 
                           + str(self.config["X"]) + " ")
        self.send_y_cmd = (self.input_device + str(self.config["EV_ABS"]) + " " 
                           + str(self.config["Y"]) + " ")
        
        logging.info("Finished initializing device.")

    def convert_GUIAction_to_send_event(self):
        """
        Takes care of converting the GUIActions from Phase 2 into Events that
        have raw commands associated with them.
        """
        # set constants to be used based on device config
        ABS_EV = self.config["EV_ABS"] + " "
        ABS_MT_PRESSURE = self.config["PRESS"] + " "
        ABS_MT_TRACKING_ID = self.config["TRACK_ID"] + " "
        ABS_MT_TOUCH_MAJOR = self.config["MAJOR"] + " "
        SYNTH_EV = self.config["EV_SYN"] + " "
        SYNTH_REPORT = self.config["EV_SYN"] + " "
        KEY_EV = self.config["EV_KEY"] + " "
        # holds events with translated commands
        send_events = []
        # placeholders
        # taps associated with each event
        curr_taps = []
        # frames associated with each event
        curr_frames = []

        # frame values begin at 1
        curr_frame = 1
        delay = 0
        frame_wait = 0
        action_type = 0
        action_duration = 0
        # how many frames it has been since last action
        paused_frames = 0
        curr_time_stamp = 1.0

        send_events.append(self.add_fake_tap())
        for curr_action in self.actions:
            raw_commands = []
            action_type = curr_action.get_type()

            # Get wait period from last event
            curr_frames = curr_action.get_frames()
            paused_frames = max(0, curr_frames[0] - curr_frame)
            curr_frame = curr_frames[len(curr_frames) - 1]
            action_duration = len(curr_frames) * FRAMES_CONV_FACTOR
            # Calculate how long to wait before the next command should be ran
            wait_per_command = (1 / FRAMES_CONV_FACTOR) / 2
            delay = paused_frames / DELAY_OFFSET
            curr_time_stamp += delay
            delay_event = Event(label="DELAY", pause_dur=delay)
            send_events.append(delay_event)

            if action_type == ActionType.CLICK:
                # click will occur at the centroid on the screen
                curr_tap = curr_action.get_centroid()
                x = (curr_tap.get_x() * (self.max_x + 1)) / self.display_width
                y = (curr_tap.get_y() * (self.max_y + 1)) / self.display_height

                # Start all tap sequences for taps
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "00000000")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + KEY_EV + "014a 00000001")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + KEY_EV + "0145 00000001")
                curr_time_stamp += wait_per_command

                # hex values looks like 0x##, so slice them to exclude 0x part
                hex_x = hex(int(x))[2:]
                hex_y = hex(int(y))[2:]
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_x_cmd + ("00000000" + hex_x)[len(hex_x):])
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_y_cmd + ("00000000" + hex_y)[len(hex_y):])
                curr_time_stamp += wait_per_command
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TOUCH_MAJOR + "00000005")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_PRESSURE + DEF_PRESSURE)
                curr_time_stamp += wait_per_command

                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                curr_time_stamp += wait_per_command

                # end tap
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "ffffffff")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                curr_time_stamp += wait_per_command

                event = Event(label="CLICK", start=Coords(curr_tap.get_x(), curr_tap.get_y()), 
                              end=Coords(curr_tap.get_x(), curr_tap.get_y()), last_event=wait_per_command)
                event.set_raw_commands(raw_commands)
                send_events.append(event)
            
            elif action_type == ActionType.LONG_CLICK:
                # click will occur at the centrin on the screen
                curr_tap = curr_action.get_centroid()
                x = (curr_tap.get_x() * (self.max_x + 1)) / self.display_width
                y = (curr_tap.get_y() * (self.max_y + 1)) / self.display_height

                # mark the beginning of the long click
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "00000000")
                curr_time_stamp += wait_per_command
                
                hex_x = hex(int(x))[2:]
                hex_y = hex(int(y))[2:]
                for i in range(len(curr_frames)):
                    # send the x, y coords of tap
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_x_cmd + ("00000000" + hex_x)[len(hex_x):])
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_y_cmd + ("00000000" + hex_y)[len(hex_y):])
                    curr_time_stamp += wait_per_command / 1.5

                    # end current section of tap
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                    curr_time_stamp += wait_per_command / 1.5

                # end long click 
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                curr_time_stamp += wait_per_command

                # End tap sequence
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "ffffffff")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                curr_time_stamp += wait_per_command

                # create event object representing the new event and add to list
                event = Event(label="LONG_CLICK", start=Coords(curr_tap.get_x(), curr_tap.get_y()),
                        end=Coords(curr_tap.get_x(), curr_tap.get_y()), 
                        last_event=wait_per_command)
                event.set_raw_commands(raw_commands)
                send_events.append(event)

            elif action_type == ActionType.SWIPE:
                curr_taps = curr_action.get_taps()
                # print("WaitPerCommand: " + wait_per_command)
                # print("SWIPE - Duration: " + action_duration + " NumOfFrames: " + len(curr_frames) + " NumOfTaps: " + len(curr_taps))

                # Start all tap sequences for swipes
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "00000000")
                curr_time_stamp += wait_per_command

                # loop through and add locations for swipe path
                for tap in curr_taps:
                    # convert coordinates to screen coordinates
                    x = (tap.get_x() * (self.max_x + 1)) / self.display_width
                    y = (tap.get_y() * (self.max_y + 1)) / self.display_height
                    
                    hex_x = hex(int(x))[2:]
                    hex_y = hex(int(y))[2:]
                    # send x and y coordinates of tap
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_x_cmd + ("00000000" + hex_x)[len(hex_x):])
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_y_cmd + ("00000000" + hex_y)[len(hex_y):])
                    curr_time_stamp += wait_per_command

                    # End tap sequence
                    raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                    curr_time_stamp += wait_per_command

                # End all tap sequences for swipes
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "ffffffff")
                raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
                curr_time_stamp += wait_per_command

                curr_tap = curr_taps[0]
                last_tap = curr_taps[len(curr_taps)-1]

                # Create event object representing the new event and add to list
                event = Event(label="SWIPE", start=Coords(curr_tap.get_x(), curr_tap.get_y()),
                        end=Coords(last_tap.get_x(), last_tap.get_y()), last_event=wait_per_command)
                event.set_raw_commands(raw_commands)
                send_events.append(event)

        self.event_list = send_events
        
    def add_fake_tap(self):
        """
        Adds a fake tap as the first event to ensure that all events are captured
        in replay.

        Returns
        -------
        fake tap event : Event
            fake tap event that can be appended to events
        """
        # set constants to be used based on device config
        ABS_EV = self.config["EV_ABS"] + " "
        ABS_MT_PRESSURE = self.config["PRESS"] + " "
        ABS_MT_TRACKING_ID = self.config["TRACK_ID"] + " "
        ABS_MT_TOUCH_MAJOR = self.config["MAJOR"] + " "
        SYNTH_EV = self.config["EV_SYN"] + " "
        SYNTH_REPORT = self.config["EV_SYN"] + " "
        KEY_EV = self.config["EV_KEY"] + " "

        raw_commands = []
        # set x and y coordinates
        x = (-1 * (self.max_x + 1)) / self.display_width
        y = (-1 * (self.max_y + 1)) / self.display_height

        curr_time_stamp = 0
        wait_per_command = 0.001
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "00000000")
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + KEY_EV + "014a 00000001")
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + KEY_EV + "0145 00000001")
        curr_time_stamp += wait_per_command

        # hex values look like -0x###, so slice to get only the digits
        hex_x = hex(int(x))[3:]
        hex_y = hex(int(y))[3:]
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_x_cmd + "ffffffff")
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.send_y_cmd + "ffffffff")
        curr_time_stamp += wait_per_command
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TOUCH_MAJOR + "00000005")
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_PRESSURE + DEF_PRESSURE)
        curr_time_stamp += wait_per_command

        # End tap location sequence
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
        curr_time_stamp += wait_per_command

        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + ABS_EV + ABS_MT_TRACKING_ID + "ffffffff")
        raw_commands.append("[    " + str(curr_time_stamp) + "] " + self.input_device + SYNTH_EV + SYNTH_REPORT + "00000000")
        curr_time_stamp += wait_per_command

        event = Event(label="CLICK", start=Coords(0, 0), end=Coords(0, 0), 
                      last_event=wait_per_command)
        event.set_raw_commands(raw_commands)

        return event

    def get_actions(self):
        """
        Returns actions detected from Phase 2.

        Returns
        -------
        actions : list of GUIActions
            actions detected in Phase2
        """
        return self.actions

    def set_actions(self, acts):
        """
        Changes actions to specified value.

        Parameters
        ----------
        acts : list of GUIActions
            new actions
        """
        self.actions = acts
   
    def extract_raw_from_events(self):
        """
        Extracts the raw commands from the events.

        Returns
        -------
        commands : list of strings
            list of raw commands associated with each event
        """
        raw_commands = []
        for event in self.event_list:
            event_comms = event.get_raw_commands()
            # add this event's commands to the total raw commands
            raw_commands.extend(event_comms)
        # set raw commands equal to these
        self.raw_commands = raw_commands
        
        return raw_commands

    def get_event_list(self):
        """
        Returns event list.

        Returns
        -------
        event_list : list of Events
            list of events detected
        """
        return self.event_list
    
    def set_event_list(self, events):
        """
        Changes event list to specified value.

        Parameters
        ----------
        events : list of Events
            new events
        """
        self.event_list = events

    def get_input_device(self):
        """
        Returns input device.

        Returns
        -------
        input_device : string
            device to be manipulated
        """
        return self.input_device

    def set_input_device(self, dev):
        """
        Changes input device to specified value.

        Parameters
        ----------
        dev : string
            new input device
        """
        self.input_device = dev
    
    def get_send_x_comm(self):
        """
        Returns send x command.

        Returns
        -------
        send_x_comm: string
            send x base command
        """
        return self.send_x_cmd

    def set_send_x_comm(self, command):
        """
        Changes send x command to specified value.
        
        Parameters
        ----------
        command : string
            new send x command
        """
        self.send_x_cmd = command

    def get_send_y_comm(self):
        """
        Returns send y command.

        Returns
        -------
        send_y_comm : string
            send y base command
        """
        return self.send_y_cmd

    def set_send_y_comm(self, command):
        """
        Changes send y command to specified value.

        Parameters
        ----------
        command : string
            new send y command
        """
        self.send_y_cmd = command

    def get_max_x(self):
        """
        Returns max x.

        Returns
        -------
        max_x : int
            max_x value
        """
        return self.max_x
    
    def set_max_x(self, max_x):
        """
        Changes max x to specified value.

        Parameters
        ----------
        max_x : int
            new max x value
        """
        self.max_x = max_x

    def get_max_y(self):
        """
        Returns max y.

        Returns
        -------
        max_y : int
            max y value
        """
        return self.max_y
    
    def set_max_y(self, max_y):
        """
        Changes max y to specified value.

        Parameters
        ----------
        max_y : int
            new max y value
        """
        self.max_y = max_y

    def get_display_width(self):
        """
        Return display width.

        Returns
        -------
        width : int
            display width
        """
        return self.display_width

    def set_display_width(self, width):
        """
        Changes display width to specified value.

        Parameters
        ----------
        width : int
            new display width
        """
        self.display_width = width

    def get_display_height(self):
        """
        Return display height.

        Returns
        -------
        height : int
            display height
        """
        return self.display_height

    def set_display_height(self, height):
        """
        Changes display height to specified value.

        Parameters
        ----------
        height : int
            new display height
        """
        self.display_height = height

    def get_config(self):
        """
        Returns device configuration.

        Returns
        -------
        config : dict
            device configuration
        """
        return self.config

    def set_config(self, config):
        """
        Changes device configuration to specified value.

        Parameters
        ----------
        config : dict
            new device configuration
        """
        self.config = config
