import os, shutil, time, subprocess
subprocess.run(["taskkill", "/F", "/IM", "CabinetStudio.exe"], capture_output=True)
time.sleep(1)
path = r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\builds\CabinetStudio"
if os.path.isdir(path):
    shutil.rmtree(path, ignore_errors=True)
print("cleared", not os.path.exists(path))
