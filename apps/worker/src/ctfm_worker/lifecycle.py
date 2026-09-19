"""Keep a calculation tied to its own supervisor, including abrupt supervisor exits."""
import os
import signal
import subprocess
import threading
import time

def guard_parent():
    parent_pid=int(os.environ.get("CTFM_PARENT_PID","0"))
    if parent_pid<=0:
        raise ValueError("Calculation requires an owning worker process")
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,parent_pid) # SYNCHRONIZE only
        if not handle:
            raise ValueError("Owning worker is no longer running")
        def parent_alive():
            return kernel.WaitForSingleObject(handle,0)==258 # WAIT_TIMEOUT
    else:
        if os.getppid()!=parent_pid:
            raise ValueError("Owning worker is no longer running")
        def parent_alive():return os.getppid()==parent_pid
    def monitor():
        while parent_alive():time.sleep(.2)
        # The worker creates a separate child group/session. Only this calculation
        # and descendants are terminated; PID reuse cannot change the parent handle.
        if os.name=="nt":
            subprocess.run(["taskkill","/PID",str(os.getpid()),"/T","/F"],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW,check=False)
        else:
            os.killpg(os.getpid(),signal.SIGKILL)
        os._exit(72)
    threading.Thread(target=monitor,name="worker-owner",daemon=True).start()
