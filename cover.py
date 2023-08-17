import dis
import sys
from typing import Any, Optional

"""
import ctypes
u8 = ctypes.c_uint8
u32 = ctypes.c_uint32
"""

def trace_func(frame: Any, event: str, arg: Optional[Any] = None):
    print(frame, event, arg)
    if event == "opcode":
        tracer.TraceOpcode(frame)
    elif event == "exception":
        tracer.TraceOpcode(frame, 1)
    elif event == "call" or event == "line":
        tracer.PushFrame(frame)
    elif event == "return":
        tracer.PopFrame(frame)

    return trace_func

class Tracer:
    def __init__(self):
        self.afl_area_ptr_ = None
        self.previous_location_ = 0
        self.current_frame_hash_ = 0

    def TraceOpcode(self, frame, is_exception=0):
        print(dis.disco(frame.f_code,frame.f_lasti),frame.f_lasti)
        current_location = self.current_frame_hash_ ^ self.HashOpcode(frame, is_exception)
        afl_map_offset = current_location ^ self.previous_location_
        #self.afl_area_ptr_[afl_map_offset % kMapSize] += 1
        self.previous_location_ = current_location >> 1

    def PushFrame(self, frame):
        frame.f_trace_lines = False
        frame.f_trace_opcodes = True
        self.current_frame_hash_ = self.HashFrame(frame)

    def PopFrame(self, frame):
        self.current_frame_hash_ = self.HashFrame(frame.f_back)

    """def ResetState(self):
        self.previous_location_ = 0

    def MapSharedMemory(self):
        env_var_value = os.getnv(kShmEnvVar)
        if not env_var_value:
            return
        shm_id = int(env_var_value)
        shmat_res = os.shmat(shm_id, None, 0)
        if shmat_res == -1:
            _exit(1)
        self.afl_area_ptr_ = ctypes.cast(shmat_res, ctypes.POINTER(u8))"""

    def StartTracing(self):
        #if self.afl_area_ptr_:
        sys.settrace(trace_func)

    def StopTracing(self):
        self.afl_area_ptr_ = None
        sys.settrace(None)

    @staticmethod
    def Hash_u32(x):
        x ^= x >> 16
        x *= 0x7feb352d
        x ^= x >> 15
        x *= 0x846ca68b
        x ^= x >> 16
        return x

    @staticmethod
    def HashFrame(frame):
        code = frame.f_code
        file_name = hash(code.co_filename)
        code_object_name = hash(code.co_name)
        first_lineno = Tracer.Hash_u32(code.co_firstlineno)
        return file_name ^ code_object_name ^ first_lineno

    @staticmethod
    def HashOpcode(frame, is_exception):
        last_opcode_index = frame.f_lasti
        return Tracer.Hash_u32(last_opcode_index ^ is_exception)

tracer = Tracer()
tracer.StartTracing()

def test():
    s = 0
    for i in range(5):
        try:
            if i % 3 == 0:
                raise Exception

                s += i
        except Exception as e:
            pass
        print(s)

test()