import math
import sys
import json
import pyaudio # Audio handling
import pvporcupine  # Porcupine hotword
import deepspeech  # Mozilla STT
import logo # k9 movement library
print("Base classes and movement library loaded...")
import numpy as np
print("Numpy active...")
import pandas as pd
print("Pandas purring...")
from state import State # Base FSM State class
print("State machine with state...")
from pvrecorder import PvRecorder # Porcupine hotword
print("Recorder, recording...")
from secrets import ACCESS_KEY # API key
print("Access key found....")
from datetime import datetime
print("Datatime known...")
from eyes import Eyes # k9 led eyes
print("Eyes open...")
from back_lights import BackLights # k9 back lights
print("Backlights on...")
from ears import K9Ears # k9 radar ears
print("Ears wiggling...")
from wolframqa import K9QA # wolfram qa skill
print("Know it all mode active...")
from k9tts import speak # speak in K9 voice
print("Speech initiated...")
import paho.mqtt.client as mqtt
print("MQTT found...")
from audio_tools import VADAudio # Voice activity detection
print("Audio tools...")
import skimage.measure as skim
print("Skikit ready to decimate...")
import depthai as dai
print("All imports done!")


detections = []
angle = 0.0

disparity_confidence_threshold = 130

sys.path.append('/home/pi/k9-chess-angular/python') 

# Create pipeline
pipeline = dai.Pipeline()

# Define sources and outputs
camRgb = pipeline.create(dai.node.ColorCamera)
spatialDetectionNetwork = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
monoLeft = pipeline.create(dai.node.MonoCamera)
monoRight = pipeline.create(dai.node.MonoCamera)
stereo = pipeline.create(dai.node.StereoDepth)

xoutRgb = pipeline.create(dai.node.XLinkOut)
xoutNN = pipeline.create(dai.node.XLinkOut)
xoutBoundingBoxDepthMapping = pipeline.create(dai.node.XLinkOut)
xoutDepth = pipeline.create(dai.node.XLinkOut)

xoutRgb.setStreamName("rgb")
xoutNN.setStreamName("detections")
xoutBoundingBoxDepthMapping.setStreamName("boundingBoxDepthMapping")
xoutDepth.setStreamName("depth")

# Properties
camRgb.setPreviewSize(300, 300)
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
camRgb.setInterleaved(False)
camRgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

monoLeft.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
monoLeft.setBoardSocket(dai.CameraBoardSocket.LEFT)
monoRight.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
monoRight.setBoardSocket(dai.CameraBoardSocket.RIGHT)

# Setting node configs
stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)

spatialDetectionNetwork.setBlobPath("./mobilenet-ssd_openvino_2021.2_6shave.blob")
spatialDetectionNetwork.setConfidenceThreshold(0.5)
spatialDetectionNetwork.input.setBlocking(False)
spatialDetectionNetwork.setBoundingBoxScaleFactor(0.5)
spatialDetectionNetwork.setDepthLowerThreshold(100)
spatialDetectionNetwork.setDepthUpperThreshold(5000)

# Linking
monoLeft.out.link(stereo.left)
monoRight.out.link(stereo.right)

camRgb.preview.link(spatialDetectionNetwork.input)

spatialDetectionNetwork.passthrough.link(xoutRgb.input)
spatialDetectionNetwork.out.link(xoutNN.input)
spatialDetectionNetwork.boundingBoxMapping.link(xoutBoundingBoxDepthMapping.input)
stereo.depth.link(spatialDetectionNetwork.inputDepth)
spatialDetectionNetwork.passthroughDepth.link(xoutDepth.input)

decimate = 20
MAX_RANGE = 4000.0
height = 400.0
width = 640.0
cx = width/decimate/2
cy = height/decimate/2
fx = 1.4 # values found by measuring known sized objects at known distances
fy = 2.05

prev_frame = 0
now_frame = 0

x_bins = pd.interval_range(start = -2000, end = 2000, periods = 40)
y_bins = pd.interval_range(start = 0, end = 1600, periods = 16)

# calculate the horizontal angle per bucket
h_bucket_fov = math.radians( 71.0 / 40.0)

print("Init of pipeline complete")

# Define K9 States   


class Waitforhotword(State):
    '''
    The child state where the k9 is waiting for the hotword
    '''
    def __init__(self):
        super(Waitforhotword, self).__init__()
        k9lights.off()
        self.porcupine = pvporcupine.create(
            access_key = ACCESS_KEY,
            keyword_paths=['/home/pi/k9localstt/canine_en_raspberry-pi_v2_1_0.ppn']
        )   
        self.recorder = PvRecorder(device_index=-1, frame_length=self.porcupine.frame_length)
        self.recorder.start()
        print(f'Using device: {self.recorder.selected_device}')
        k9eyes.set_level(0.001)
        while True:
            pcm = self.recorder.read()
            result = self.porcupine.process(pcm)
            if result >= 0:
                print('Detected hotword')
                self.on_event('hotword_detected')

    def on_event(self, event):
        if event == 'hotword_detected':
            if self.porcupine is not None:
                self.porcupine.delete()
            if self.recorder is not None:
                self.recorder.delete()
            return Listening()
        return self


class Listening(State):
    '''
    The child state where K9 is now listening for an utterance
    '''
    def __init__(self):
        super(Listening, self).__init__()
        self.vad_audio = VADAudio(aggressiveness=1,
        device=None,
        input_rate=16000,
        file=None)
        self.stream_context = model.createStream()
        print("Listening: init complete")
        k9eyes.set_level(0.01)
        k9lights.on()
        while True:
            self.frames = self.vad_audio.vad_collector()
            for frame in self.frames:
                if frame is not None:
                    self.stream_context.feedAudioContent(np.frombuffer(frame, np.int16))
                else:
                    print("Stream finished")
                    self.command = self.stream_context.finishStream()
                    del self.stream_context
                    print("Listen.run() - I heard:",self.command)
                    if self.command != "":
                        self.vad_audio.destroy()
                        self.on_event('command_received')
                    else:
                        self.stream_context = model.createStream()

    def on_event(self, event):
        if event == 'command_received':
            return Responding(self.command)
        return self


class Responding(State):
    '''
    The child state where K9 processes a response to the text
    if command is not understood, Wolfram Mathematica will be
    used to retrieve a result
    '''
    def __init__(self, command):
        super(Responding, self).__init__()
        self.command = command
        print("Responding.init() - started")
        print(self.command)
        k9eyes.set_level(0.5)
        if 'listen' in self.command:
            speak("No longer listening")
            self.on_event('stop_listening')
        if ('here' in self.command) or ('over' in self.command):
            speak("Coming master")
            self.on_event('scanning')
        if 'follow' in self.command:
            speak("Folllowing master")
            self.on_event('follow')
        k9ears.think()
        answer = k9qa.ask_question(self.command)
        k9ears.stop()
        speak(answer)
        self.on_event('responded')

    def on_event(self, event):
        if event == 'responded':
            return Listening()
        if event == 'stop_listening':
            return Waitforhotword()
        if event == 'scanning':
            return Scanning()
        if event == 'follow':
            return Following()
        return self


class Scanning(State):
    '''
    The state where K9 is looking for the nearest person to follow
    '''
    def __init__(self):
        super(Scanning, self).__init__()
        speak("Scanning")
        while True:
            self.target = None
            self.target = person_scan()
            if self.target is not None :
                self.on_event('person_found')

    def on_event(self, event):
        if event == 'person_found':
            return Turning(self.target)
        return self


class Turning(State):
    '''
    The child state where K9 is turning towards the target person
    '''
    def __init__(self, target):
        super(Turning, self).__init__()
        self.target = target
        z = float(self.target.depth_z)
        x = float(self.target.depth_x)
        angle = ( math.pi / 2 ) - math.atan2(z, x)
        if abs(angle) > 0.2 :
            print("Turning: Moving ",angle," radians towards target")
            logo.right(angle)
        else:
            self.on_event('turn_finished')
        while True:
            if logo.finished_move():
                self.on_event('turn_finished')

    def on_event(self, event):
        if event == 'turn_finished':
            return Moving_Forward(self.target)
        return self


class Moving_Forward(State):
    '''
    The child state where K9 is moving forwards to the target
    '''
    def __init__(self, target):
        super(Moving_Forward, self).__init__()
        self.target = target
        # self.avg_dist = 4.0
        z = float(self.target.depth_z)
        distance = float(z - SWEET_SPOT)
        if distance > 0:
            print("Moving Forward: target is",z,"m away. Moving",distance,"m")
            logo.forwards(distance)
        while True:
            if not logo.finished_move():
                pass
            else:
                self.on_event('target_reached')

    def on_event(self, event):
        if event == 'target_reached':
            return Following()
        return self


class Following(State):
    '''
    Having reached the target, now follow it blindly
    '''
    def __init__(self):
        super(Following, self).__init__()
        logo.stop()
        speak("Mastah!")
        while True:
            depth_image = self.scan(min_range = 200.0, max_range = 1500.0,)
            if depth_image is not None:
                direction, distance = self.follow_vector(depth_image, certainty = CONF)
                if distance is not None and direction is not None:
                    distance = distance / 1000.0
                    print("Following: direction:", direction, "distance:", distance)
                    angle = direction * math.radians(77.0)
                    move = (distance - SWEET_SPOT)
                    print("Following: angle:", angle, "move:", move)
                    damp_angle = 3.0
                    damp_distance = 2.0
                    if abs(angle) >= (0.1 * damp_angle) :
                        logo.rt(angle / damp_angle, fast = True)
                    else:
                        if abs(move) >= (0.05 * damp_distance) :
                            logo.fd(move / damp_distance)

    def on_event(self, event):
        if event == 'assistant_mode':
            return Waitforhotword()
        return self

MAX_DIST = 1.5
MIN_DIST = 0.3
CONF = 0.7
SWEET_SPOT = MIN_DIST + (MAX_DIST - MIN_DIST) / 2.0


model = deepspeech.Model("/home/pi/k9localstt/deepspeech-0.9.3-models.tflite")
model.enableExternalScorer("/home/pi/k9localstt/deepspeech-0.9.3-models.scorer")

print("Deepspeech loaded")

k9eyes = Eyes()
k9lights = BackLights()
k9ears = K9Ears()
k9qa = K9QA()

class K9(object):
    '''
    A K9 finite state machine that starts in waiting state and
    will transition to a new state on when a transition event occurs.
    It also supports a run command to enable each state to have its
    own specific behaviours
    '''

    def __init__(self):
        ''' Initialise K9 in his waiting state. '''

        self.last_message = ""
        self.client = mqtt.Client("k9-python")
        self.client.connect("localhost")
        self.client.on_message = self.mqtt_callback # attach function to callback
        self.client.subscribe("/ble/advertise/watch/m")
        k9lights.on()
        k9eyes.set_level(1)
        k9ears.scan()
        speak("K9 is active")
        k9lights.off()
        k9eyes.set_level(0)
        k9ears.stop()
        self.state = Waitforhotword()

    def on_event(self,event):
        '''
        Process the incoming event using the on_event function of the
        current K9 state.  This may result in a change of state.
        '''

        # The next state will be the result of the on_event function.
        print("Event:",event, "raised in state", str(self.state).lower())
        self.state = self.state.on_event(event)

    def mqtt_callback(self,client, userdata, message):
        """
        Enables K9 to receive a message from an Epruino Watch via
        MQTT over Bluetooth (BLE) to place it into active or inactive States
        """

        payload = str(message.payload.decode("utf-8"))
        if payload != self.last_message:
            self.last_message = payload
            event = payload[3:-1].lower()
            # print("Event: ",str(event))
            self.on_event(event)

def person_scan():
    '''
    Returns detectd person nearest centre of field

    detection.label == 15

    '''

    with dai.Device(pipeline) as device:
        detectionNNQueue = device.getOutputQueue(name="detections", maxSize=4, blocking=False)
        inDet = detectionNNQueue.get()
        detections = inDet.detections
        if detections is not None :
            people = [detection for detection in detections
                        if detection.label == 15
                        if detection.confidence > CONF]
            if len(people) >= 1 :
                min_angle = math.pi
                for person in people:
                    z = float(person.depth_z)
                    x = float(person.depth_x)
                    angle = abs(( math.pi / 2 ) - math.atan2(z, x))
                    if angle < min_angle:
                        min_angle = angle
                        target = person
                return target

def scan(min_range = 500.0, max_range = 1200.0, decimate_level = 20, mean = True):
    '''
    Generate a simplified image of the depth image stream from the camera.  This image
    can be reduced in size by using the decimate_level parameter.  
    It also will remove invalid data from the image (too close or too near pixels)
    The mechanism to determine the returned value of each new pixel can be the mean or 
    minimum values across the area can also be specified.
    
    The image is returned as a 2D numpy array.
    '''

    func = np.mean if mean else np.min
    with dai.Device(pipeline) as device:
        depthQueue = device.getOutputQueue(name="depth", maxSize=4, blocking=False)
        depth = depthQueue.get()
        frame = depth.getFrame()
        valid_frame = (frame >= min_range) & (frame <= max_range)
        valid_image = np.where(valid_frame, frame, max_range)
        decimated_valid_image = skim.block_reduce(valid_image,(decimate_level,decimate_level),func)
        return decimated_valid_image

def point_cloud(frame, min_range = 200.0, max_range = 4000.0):
    '''
    Generates a point cloud based on the provided numpy 2D depth array.
    
    Returns a 16 x 40 numpy matrix describing the forward distance to
    the points within the field of view of the camera.
    
    Initial measures closer than the min_range are discarded.  Those outside of the
    max_range are set to the max_range.
    '''

    height, width = frame.shape
    # Convert depth map to point cloud with valid depths
    column, row = np.meshgrid(np.arange(width), np.arange(height), sparse=True)
    valid = (frame >= min_range) & (frame <= max_range)
    global test_image
    test_image = np.where(valid, frame, max_range)
    z = np.where(valid, frame, 0.0)
    x = np.where(valid, (z * (column - cx) /cx / fx) + 120.0 , max_range)
    y = np.where(valid, 325.0 - (z * (row - cy) / cy / fy) , max_range)
    # Flatten point cloud axes
    z2 = z.flatten()
    x2 = x.flatten()
    y2 = y.flatten()
    # Stack the x, y and z co-ordinates into a single 2D array
    cloud = np.column_stack((x2,y2,z2))
    # Filter the array by x and y co-ordinates
    in_scope = (cloud[:,1] < 1600) & (cloud[:,1] > 0) & (cloud[:,0] < 2000) & (cloud[:,0] > -2000)
    in_scope = np.repeat(in_scope, 3)
    in_scope = in_scope.reshape(-1, 3)
    scope = np.where(in_scope, cloud, np.nan)
    # Remove invalid rows from array
    scope = scope[~np.isnan(scope).any(axis=1)]
    # Index each point into 10cm x and y bins (40 x 16)
    x_index = pd.cut(scope[:,0], x_bins)
    y_index = pd.cut(scope[:,1], y_bins)
    # Place the depth values into the corresponding bin
    binned_depths = pd.Series(scope[:,2])
    # Average the depth measures in each bin
    totals = binned_depths.groupby([y_index, x_index]).mean()
    # Reshape the bins into a 16 x 40 matrix
    totals = totals.values.reshape(16,40)
    return totals

def follow_vector(image, max_range = 1200.0, certainty = 0.75):
    """
    Determine direction and distance to person to approach
    """
    final_distance = None
    direction = None
    # determine size of supplied image
    height, width = image.shape
    # just use the top half for analysis
    # as this will ignore low obstacles
    half_height = int(height/2)
    image = image[0:half_height,:]
    # find all the columns within the image where there are a
    # consistently significant number of valid depth measurements
    # this suggests a target in range that is reasonably tall
    # and vertical (hopefully a person's legs
    columns = np.sum(image < max_range, axis = 0) >= (certainty*half_height)
    # average the depth values of each column
    distance = np.average(image, axis = 0)
    # create an array with just the useful distances (by zeroing
    # out any columns with inconsistent data)
    useful_distances = distance * columns
    # average out all the useful distances
    # ignoring the zeros and the max_ranges
    subset = useful_distances[np.where((useful_distances < max_range) & (useful_distances > 0.0))]
    if len(subset) > 0:
        final_distance = np.average(subset)
    # determine the indices of the valid columns and average them
    # us the size of the image to determine a relative strength of
    # direction that can be converted into an angle once fov of
    # camera is known (range is theoretically -1 to +1 that
    # corresponds to the h_fov of the camera)
    mid_point = (width - 1.0) / 2.0
    indices = columns.nonzero()
    if len(indices[0]) > 0 :
        direction = (np.average(indices) - mid_point) / width
    return (direction, final_distance)

try:
    print("Creating K9 instance")
    k9 = K9()
except KeyboardInterrupt:
    logo.stop()
    k9.client.loop_stop()
    speak("Inactive")
    print('Exiting from', str(k9.state).lower(),'state.')
    k9lights.off()
    k9eyes.set_level(0)
    sys.exit(0) 