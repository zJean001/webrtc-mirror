#!/usr/bin/env python
# Copyright (c) 2017 The WebRTC project authors. All Rights Reserved.
#
# Use of this source code is governed by a BSD-style license
# that can be found in the LICENSE file in the root of the source
# tree. An additional intellectual property rights grant can be found
# in the file PATENTS.  All contributing project authors may
# be found in the AUTHORS file in the root of the source tree.

import optparse
import os
import subprocess
import sys
import time
import glob
import re

# Used to time-stamp output files and directories
CURRENT_TIME = time.strftime("%d_%m_%Y-%H:%M:%S")

def _ParseArgs():
  """Registers the command-line options."""
  usage = 'usage: %prog [options]'
  parser = optparse.OptionParser(usage=usage)

  parser.add_option('--frame_width', type='string', default='1280',
                    help='Width of the recording. Default: %default')
  parser.add_option('--frame_height', type='string', default='720',
                    help='Height of the recording. Default: %default')
  parser.add_option('--framerate', type='string', default='60',
                    help='Recording framerate. Default: %default')
  parser.add_option('--ref_duration', type='string', default='20',
                    help='Reference recording duration. Default: %default')
  parser.add_option('--test_duration', type='string', default='10',
                    help='Test recording duration. Default: %default')
  parser.add_option('--time_between_recordings', type=float, default=5,
                    help='Time between starting test recording after ref.'
                    'Default: %default')
  parser.add_option('--ref_video_device', type='string', default='/dev/video0',
                    help='Reference recording device. Default: %default')
  parser.add_option('--test_video_device', type='string', default='/dev/video1',
                    help='Test recording device. Default: %default')
  parser.add_option('--app_name', type='string',
                    help='Name of the app under test.')
  parser.add_option('--recording_api', type='string', default='Video4Linux2',
                    help='Recording API to use. Default: %default')
  parser.add_option('--pixel_format', type='string', default='yuv420p',
                    help='Recording pixel format Default: %default')
  parser.add_option('--ffmpeg', type='string',
                    help='Path to the ffmpeg executable for the reference '
                    'device.')
  parser.add_option('--video_container', type='string', default='yuv',
                    help='Video container for the recordings.'
                    'Default: %default')
  parser.add_option('--compare_videos_script', type='string',
                    default='compare_videos.py',
                    help='Path to script used to compare and generate metrics.'
                    'Default: %default')
  parser.add_option('--frame_analyzer', type='string',
                    default='../../out/Default/frame_analyzer',
                    help='Path to the frame analyzer executable.'
                    'Default: %default')
  parser.add_option('--zxing_path', type='string',
                    help='Path to the zebra xing barcode analyzer.')
  parser.add_option('--ref_rec_dir', type='string', default='ref',
                    help='Path to where reference recordings will be created.'
                    'Ideally keep the ref and test directories on separate'
                    'drives. Default: %default')
  parser.add_option('--test_rec_dir', type='string', default='test',
                    help='Path to where test recordings will be created.'
                    'Ideally keep the ref and test directories on separate '
                    'drives. Default: %default')
  parser.add_option('--test_crop_parameters', type='string',
                    help='ffmpeg processing parameters for the test video.')
  parser.add_option('--ref_crop_parameters', type='string',
                    help='ffmpeg processing parameters for the ref video.')

  options, _ = parser.parse_args()

  if not options.app_name:
    parser.error('You must provide an application name!')

  if not options.test_crop_parameters or not options.ref_crop_parameters:
    parser.error('You must provide ref and test crop parameters!')

  # Ensure the crop filter is included in the crop parameters used for ffmpeg.
  if 'crop' not in options.ref_crop_parameters:
    parser.error('You must provide a reference crop filter for ffmpeg.')
  if 'crop' not in options.test_crop_parameters:
    parser.error('You must provide a test crop filter for ffmpeg.')

  if not options.ffmpeg:
    parser.error('You most provide location for the ffmpeg executable.')
  if not os.path.isfile(options.ffmpeg):
    parser.error('Cannot find the ffmpeg executable.')

  # compare_videos.py dependencies.
  if not os.path.isfile(options.compare_videos_script):
    parser.warning('Cannot find compare_videos.py script, no metrics will be '
                   'generated!')
  if not os.path.isfile(options.frame_analyzer):
    parser.warning('Cannot find frame_analyzer, no metrics will be generated!')
  if not os.path.isfile(options.zxing_path):
    parser.warning('Cannot find Zebra Xing, no metrics will be generated!')

  return options


def CreateRecordingDirs(options):
  """Create root + sub directories for reference and test recordings.

  Args:
    options(object): Contains all the provided command line options.
  Return:
    record_paths(dict): key: value pair with reference and test file
        absolute paths.
  """

  # Create root directories for the video recordings.
  if not os.path.isdir(options.ref_rec_dir):
    os.makedirs(options.ref_rec_dir)
  if not os.path.isdir(options.test_rec_dir):
    os.makedirs(options.test_rec_dir)

  # Create and time-stamp directories for all the output files.
  ref_rec_dir = os.path.join(options.ref_rec_dir, options.app_name + '_' + \
    CURRENT_TIME)
  test_rec_dir = os.path.join(options.test_rec_dir, options.app_name + '_' + \
    CURRENT_TIME)

  os.makedirs(ref_rec_dir)
  os.makedirs(test_rec_dir)

  record_paths = {
    'ref_rec_location' : os.path.abspath(ref_rec_dir),
    'test_rec_location' : os.path.abspath(test_rec_dir)
  }

  return record_paths


def RestartMagewellDevices(ref_video_device, test_video_device):
  """Reset the USB ports where Magewell capture devices are connected to.

  Tries to find the provided ref_video_device and test_video_device devices
  which use video4linux and then do a soft reset by using USB unbind and bind.
  This is due to Magewell capture devices have proven to be unstable after the
  first recording attempt.

  Args:
    ref_video_device(string): reference recording device path.
    test_video_device(string): test recording device path
  """

  # Get the dev/videoN device name from the command line arguments.
  ref_magewell = ref_video_device.split('/')[2]
  test_magewell = test_video_device.split('/')[2]

  # Find the device location including USB and USB Bus ID's.
  device_string = '/sys/bus/usb/devices/usb*/**/**/video4linux/'
  ref_magewell_device = glob.glob('%s%s' % (device_string, ref_magewell))
  test_magewell_device = glob.glob('%s%s' % (device_string, test_magewell))

  magewell_usb_ports = []

  # Figure out the USB bus and port ID for each device.
  ref_magewell_path = str(ref_magewell_device).split('/')
  for directory in ref_magewell_path:

    # Find the folder with pattern "N-N", e.g. "4-3" or \
    # "[USB bus ID]-[USB port]"
    if re.match(r'^\d-\d$', directory):
      magewell_usb_ports.append(directory)

  test_magewell_path = str(test_magewell_device).split('/')
  for directory in test_magewell_path:

    # Find the folder with pattern "N-N", e.g. "4-3" or \
    # "[USB bus ID]-[USB port]"
    if re.match(r'^\d-\d$', directory):
      magewell_usb_ports.append(directory)

  print '\nResetting USB ports where magewell devices are connected...'

  # Use the USB bus and port ID (e.g. 4-3) to unbind and bind the USB devices
  # (i.e. soft eject and insert).
  try:
    for usb_port in magewell_usb_ports:
      echo_cmd = ['echo', usb_port]
      unbind_cmd = ['sudo', 'tee', '/sys/bus/usb/drivers/usb/unbind']
      bind_cmd = ['sudo', 'tee', '/sys/bus/usb/drivers/usb/bind']

      # TODO(jansson) Figure out a way to call on echo once for bind & unbind
      # if possible.
      echo_unbind = subprocess.Popen(echo_cmd, stdout=subprocess.PIPE)
      unbind = subprocess.Popen(unbind_cmd, stdin=echo_unbind.stdout)
      echo_unbind.stdout.close()
      unbind.communicate()
      unbind.wait()

      echo_bind = subprocess.Popen(echo_cmd, stdout=subprocess.PIPE)
      bind = subprocess.Popen(bind_cmd, stdin=echo_bind.stdout)
      echo_bind.stdout.close()
      bind.communicate()
      bind.wait()
  except OSError as e:
    print 'Error while resetting magewell devices: ' + e
    raise

  print 'Reset done!\n'


def StartRecording(options, record_paths):
  """Starts recording from the two specified video devices.

  Args:
    options(object): Contains all the provided command line options.
    record_paths(dict): key: value pair with reference and test file
        absolute paths.
  """
  ref_file_name = '%s_%s_ref.%s' % (options.app_name, CURRENT_TIME,
    options.video_container)
  ref_file_location = os.path.join(record_paths['ref_rec_location'],
      ref_file_name)

  test_file_name = '%s_%s_test.%s' % (options.app_name, CURRENT_TIME,
    options.video_container)
  test_file_location = os.path.join(record_paths['test_rec_location'],
      test_file_name)

  # Reference video recorder command line.
  ref_cmd = [
    options.ffmpeg,
    '-v', 'error',
    '-s', options.frame_width + 'x' + options.frame_height,
    '-framerate', options.framerate,
    '-f', options.recording_api,
    '-i', options.ref_video_device,
    '-pix_fmt', options.pixel_format,
    '-s', options.frame_width + 'x' + options.frame_height,
    '-t', options.ref_duration,
    '-framerate', options.framerate,
    ref_file_location
  ]

  # Test video recorder command line.
  test_cmd = [
    options.ffmpeg,
    '-v', 'error',
    '-s', options.frame_width + 'x' + options.frame_height,
    '-framerate', options.framerate,
    '-f', options.recording_api,
    '-i', options.test_video_device,
    '-pix_fmt', options.pixel_format,
    '-s', options.frame_width + 'x' + options.frame_height,
    '-t', options.test_duration,
    '-framerate', options.framerate,
    test_file_location
  ]
  print 'Trying to record from reference recorder...'
  ref_recorder = subprocess.Popen(ref_cmd, stderr=sys.stderr)

  # Start the 2nd recording a little later to ensure the 1st one has started.
  # TODO(jansson) Check that the ref_recorder output file exists rather than
  # using sleep.
  time.sleep(options.time_between_recordings)
  print 'Trying to record from test recorder...'
  test_recorder = subprocess.Popen(test_cmd, stderr=sys.stderr)
  test_recorder.wait()
  ref_recorder.wait()

  # ffmpeg does not abort when it fails, need to check return code.
  assert ref_recorder.returncode == 0, (
    'Ref recording failed, check ffmpeg output and device: %s'
    % options.ref_video_device)
  assert test_recorder.returncode == 0, (
    'Test recording failed, check ffmpeg output and device: %s'
    % options.test_video_device)

  print 'Ref file recorded to: ' + os.path.abspath(ref_file_location)
  print 'Test file recorded to: ' + os.path.abspath(test_file_location)
  print 'Recording done!\n'
  return FlipAndCropRecordings(options, test_file_name,
    record_paths['test_rec_location'], ref_file_name,
    record_paths['ref_rec_location'])


def FlipAndCropRecordings(options, test_file_name, test_file_location,
                          ref_file_name, ref_file_location):
  """Performs a horizontal flip of the reference video to match the test video.

  This is done to the match orientation and then crops the ref and test videos
  using the options.test_crop_parameters and options.ref_crop_parameters.

  Args:
    options(object): Contains all the provided command line options.
    test_file_name(string): Name of the test video file recording.
    test_file_location(string): Path to the test video file recording.
    ref_file_name(string): Name of the reference video file recording.
    ref_file_location(string): Path to the reference video file recording.
  Return:
    recording_files_and_time(dict): key: value pair with the path to cropped
        test and reference video files.
  """
  print 'Trying to crop videos...'

  # Ref file cropping.
  cropped_ref_file_name = 'cropped_' + ref_file_name
  cropped_ref_file = os.path.abspath(
      os.path.join(ref_file_location, cropped_ref_file_name))

  ref_video_crop_cmd = [
    options.ffmpeg,
    '-v', 'error',
    '-s', options.frame_width + 'x' + options.frame_height,
    '-i', os.path.join(ref_file_location, ref_file_name),
    '-vf', options.ref_crop_parameters,
    '-c:a', 'copy',
    cropped_ref_file
  ]

  # Test file cropping.
  cropped_test_file_name = 'cropped_' + test_file_name
  cropped_test_file = os.path.abspath(
      os.path.join(test_file_location, cropped_test_file_name))

  test_video_crop_cmd = [
    options.ffmpeg,
    '-v', 'error',
    '-s', options.frame_width + 'x' + options.frame_height,
    '-i', os.path.join(test_file_location, test_file_name),
    '-vf', options.test_crop_parameters,
    '-c:a', 'copy',
    cropped_test_file
  ]

  ref_crop = subprocess.Popen(ref_video_crop_cmd)
  ref_crop.wait()
  print 'Ref file cropped to: ' + cropped_ref_file

  try:
    test_crop = subprocess.Popen(test_video_crop_cmd)
    test_crop.wait()
    print 'Test file cropped to: ' + cropped_test_file
    print 'Cropping done!\n'

    # Need to return these so they can be used by other parts.
    cropped_recordings = {
      'cropped_test_file' : cropped_test_file,
      'cropped_ref_file' : cropped_ref_file
    }

    return cropped_recordings
  except subprocess.CalledProcessError as e:
    print 'Something went wrong during cropping: ' + e
    raise


def CompareVideos(options, recording_result):
  """Runs the compare_video.py script from src/webrtc/tools using the file path.

  Uses the path from recording_result and writes the output to a file named
  <options.app_name + '_' + CURRENT_TIME + '_result.txt> in the reference video
  recording folder taken from recording_result.

  Args:
    options(object): Contains all the provided command line options.
    recording_files_and_time(dict): key: value pair with the path to cropped
    test and reference video files
  """
  print 'Starting comparison...'
  print 'Grab a coffee, this might take a few minutes...'
  cropped_ref_file = recording_result['cropped_ref_file']
  cropped_test_file = recording_result['cropped_test_file']
  compare_videos_script = os.path.abspath(options.compare_videos_script)
  rec_path = os.path.abspath(os.path.join(
    os.path.dirname(recording_result['cropped_ref_file'])))
  result_file_name = os.path.join(rec_path, '%s_%s_result.txt') % (
    options.app_name, CURRENT_TIME)

  # Find the crop dimensions (950 and 420) in the ref crop parameter string:
  # 'hflip, crop=950:420:130:56'
  for param in options.ref_crop_parameters.split('crop'):
    if param[0] == '=':
      crop_width = param.split(':')[0].split('=')[1]
      crop_height = param.split(':')[1]

  compare_cmd = [
    sys.executable,
    compare_videos_script,
    '--ref_video', cropped_ref_file,
    '--test_video', cropped_test_file,
    '--frame_analyzer', os.path.abspath(options.frame_analyzer),
    '--zxing_path', options.zxing_path,
    '--ffmpeg_path', options.ffmpeg,
    '--stats_file_ref', os.path.join(os.path.dirname(cropped_ref_file),
        cropped_ref_file + '_stats.txt'),
    '--stats_file_test', os.path.join(os.path.dirname(cropped_test_file),
        cropped_test_file + '_stats.txt'),
    '--yuv_frame_height', crop_height,
    '--yuv_frame_width', crop_width
  ]

  try:
    with open(result_file_name, 'w') as f:
      compare_video_recordings = subprocess.Popen(compare_cmd, stdout=f)
      compare_video_recordings.wait()
      print 'Result recorded to: ' + os.path.abspath(result_file_name)
      print 'Comparison done!'
  except subprocess.CalledProcessError as e:
    print 'Something went wrong when trying to compare videos: ' + e
    raise


def main():
  """The main function.

  A simple invocation is:
  ./run_video_analysis.py \
    --app_name AppRTCMobile \
    --ffmpeg ./ffmpeg --ref_video_device=/dev/video0 \
    --test_video_device=/dev/video1 \
    --zxing_path ./zxing \
    --test_crop_parameters 'crop=950:420:130:56' \
    --ref_crop_parameters 'hflip, crop=950:420:130:56' \
    --ref_rec_dir /tmp/ref \
    --test_rec_dir /tmp/test

  This will produce the following files if successful:
  # Original video recordings.
  /tmp/ref/AppRTCMobile_<recording date and time>_ref.yuv
  /tmp/test/AppRTCMobile_<recording date and time>_test.yuv

  # Cropped video recordings according to the crop parameters.
  /tmp/ref/cropped_AppRTCMobile_<recording date and time>_ref.yuv
  /tmp/test/cropped_AppRTCMobile_<recording date and time>_ref.yuv

  # Comparison metrics from cropped test and ref videos.
  /tmp/test/AppRTCMobile_<recording date and time>_result.text

  """
  options = _ParseArgs()
  RestartMagewellDevices(options.ref_video_device, options.test_video_device)
  record_paths = CreateRecordingDirs(options)
  recording_result = StartRecording(options, record_paths)

  # Do not require compare_video.py script to run, no metrics will be generated.
  if options.compare_videos_script:
    CompareVideos(options, recording_result)
  else:
    print ('Skipping compare videos step due to compare_videos flag were not '
           'passed.')


if __name__ == '__main__':
  sys.exit(main())