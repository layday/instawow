from setuptools import setup

setup(
    name='instawow_test_plugin',
    py_modules=['instawow_test_plugin'],
    entry_points={'instawow.plugins': ['instawow_test_plugin = instawow_test_plugin']},
)
