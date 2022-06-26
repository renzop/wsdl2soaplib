This project is based on a script by StackOverflow's user optilude that he posted in the following answer:

http://stackoverflow.com/questions/3083186/generating-python-soaplib-stubs-from-wsdl/3086597#3086597



HOW TO USE IT:

$ wsdl2soaplib <url or filename of WSDL> [<username> <password>] > out.py

This branch by user renzop went in a different direction. It creates Python dataclasses for the interface which can
be used for development of any python package without using the zope library. One missing feature is, that it does not
create the response object classes of the services.

    @dataclass
    class ExampleClass:
        id: int = 0
        timestamp: float = 0
        state: int = 0
