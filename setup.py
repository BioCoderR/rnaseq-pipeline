from setuptools import setup, find_packages

setup(name='rnaseq_pipeline',
      packages=find_packages(),
      install_requires=['luigi==2.8.13', 'bioluigi', 'PyYAML', 'requests', 'pandas', 'Flask'])
