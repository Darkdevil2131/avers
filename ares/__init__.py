"""ARES evidence workspace. Disable dependency telemetry before runtime imports."""
import os
os.environ['ORT_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
