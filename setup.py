from setuptools import setup, find_packages


with open('requirements.txt') as f:
    install_requires = [d for d in f.read().splitlines() if d and not d.startswith('#')]

for i, d in enumerate(install_requires):
    if d.startswith('git+'):
        pkg = d.split('#egg=')[1]
        install_requires[i] = f'{pkg} @ {d}'

setup(
    name='proxmox_desktop',
    version='0.0.1',
    install_requires=install_requires,
    packages=find_packages(
        where='.',
        include=['proxmox_desktop*'],
    ),
    entry_points={
        'console_scripts': [
            'proxmox-desktop = proxmox_desktop.proxmox_desktop:main',
            'proxmox-viewer = proxmox_desktop.proxmox_viewer:main',
            'test-pycharm-debugger = proxmox_desktop.test_debugger:main'
        ]
    }
)
