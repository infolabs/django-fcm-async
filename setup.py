from setuptools import setup, find_packages


setup(
    name='django-fcm-async',
    version=__import__('fcm_async').__version__,
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        'requests>=2.22.0',
        'urllib3>=1.25.7',
        'Django>=1.9.8',
        'django-post-office>=3.1.0',
        'firebase-admin>=3.2.0'
    ],
    package_data={
        'fcm_async': [
            'locale/*/LC_MESSAGES/*',
            'static/fcm_async/*',
        ],
    },
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Framework :: Django',
    ]
)
