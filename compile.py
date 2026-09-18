import os
import PyInstaller.__main__

args = [
    'lockscreen_date.py',
    '--name=CustomLockScreenDate',
    '--icon=nugget.ico',
    '--onedir',
    '--windowed',
    '--noconfirm',
    '--collect-all=pymobiledevice3',
    '--add-data=nugget.ico;.',
    '--copy-metadata=pyimg4',
    '--hidden-import=pyimg4',
    '--hidden-import=zeroconf',
    '--hidden-import=zeroconf._utils.ipaddress',
    '--hidden-import=zeroconf._handlers.answers',
]

if os.name == 'nt' and os.path.exists('version.txt'):
    args.append('--version-file=version.txt')

PyInstaller.__main__.run(args)
