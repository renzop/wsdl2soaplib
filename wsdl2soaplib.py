#! /usr/bin/env python

import keyword
import os.path
import re
import sys
import textwrap

import suds.client

VALID_IDENTIFIER_RE = re.compile(r"[_A-Za-z][_A-Za-z1-9]*")
VALID_IDENTIFIER_FIRST_LETTER_RE = re.compile(r"[_A-Za-z]")
VALID_IDENTIFIER_SUBSEQUENT_LETTER_RE = re.compile(r"[_A-Za-z1-9]")

HEADER = '''\
"""SOAP web services generated from:
{wsdl}.
with: https://github.com/renzop/wsdl2soaplib
"""
from dataclasses import dataclass
from enum import Enum, auto

'''

INTERFACE = '''\
@dataclass
class {name}:
    """{docstring}"""
'''

SERVICE_INTERFACE_DOCSTRING = '''\
SOAP service ``{service_name}`` with target namespace {tns}.
'''

TYPE_INTERFACE_DOCSTRING = '''\
SOAP {type} ``{{{namespace}}}{name}``
'''

TYPE_MAP = '''\
WSDL_TYPES = {{
{items}
}}


'''

SOAPMETHOD = '''    @soap({args}_returns={response})'''

METHOD = '''    def {name}(self{args}):'''

METHOD_DOCSTRING = '''\
        """
        Returns: {response}
        """\
'''

DEFAULT_RETURN = '''\
        return self.client.{method}({args})

'''

STANDARD_TYPE_NAMESPACES = (
    'http://schemas.xmlsoap.org/soap/encoding/',
    'http://schemas.xmlsoap.org/wsdl/',
    'http://www.w3.org/2001/XMLSchema'
)

SCHEMA_TYPE_MAPPING = {
    None: '{type_name}',

    'None': 'Null',

    'boolean': 'bool',
    'string': 'str',

    'integer': 'int',
    'long': 'int',
    'int': 'int',
    'short': 'int',
    'byte': 'int',

    'unsignedLong': 'int',
    'unsignedInt': 'int',
    'unsignedShort': 'int',
    'unsignedByte': 'int',

    'positiveInteger': 'int',
    'nonPositiveInteger': 'int',
    'negativeInteger': 'int',
    'nonNegativeInteger': 'int',

    'float': 'float',
    'double': 'float',

    'decimal': 'Decimal',

    'dateTime': 'DateTime',
    'date': 'Date',

    'anyURI': 'AnyUri',
    'token': 'str',
    'normalizedString': 'str',

    'base64Binary': 'str',
    'hexBinary': 'str',
}

DEFAULT_VALUE_MAPPING = {
    'int': 0,
    'float': 0,
    'str': "''",
    'bool': False
}

def format_docstring(text, indent=4, colwidth=78):
    width = colwidth - indent
    joiner = '\n' + ' ' * indent
    return joiner.join(textwrap.wrap(text, width) + [''])


def type_name(type_):
    resolved = type_.resolve()
    return resolved.name or ''

def to_snake_case(name):
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('__([A-Z])', r'_\1', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name)
    return name.lower()


def schema_type_name(type_, deps=None):
    resolved = type_.resolve()
    name = resolved.name or ''

    schema_type = SCHEMA_TYPE_MAPPING.get(name)
    if schema_type is None:  # not a standard type

        # user default
        schema_type = SCHEMA_TYPE_MAPPING[None]

        # possibly save dependency link
        if deps is not None:
            deps.append(name)

    required = type_.required()
    schema_type = schema_type.format(type_name=name, required=required)

    # if type_.unbounded():
    #     schema_type = 'Array({0})'.format(schema_type)

    return schema_type


def normalize_identifier(identifier):
    if not VALID_IDENTIFIER_RE.match(identifier):
        new_identifier_letters = []
        first_letter = True
        for letter in identifier:
            if first_letter:
                if VALID_IDENTIFIER_FIRST_LETTER_RE.match(letter):
                    new_identifier_letters.append(letter)
                else:
                    new_identifier_letters.append('_')
                first_letter = False
            else:
                if VALID_IDENTIFIER_SUBSEQUENT_LETTER_RE.match(letter):
                    new_identifier_letters.append(letter)
                else:
                    new_identifier_letters.append('_')
        identifier = ''.join(new_identifier_letters)

    if keyword.iskeyword(identifier):
        identifier = identifier + '_'

    return identifier


def get_header(url):
    return HEADER.format(wsdl=url)


def get_printed_types(service_def_types, standard_type_namespaces):
    # Types
    type_names = []
    type_map = {}
    type_seq = []
    type_deps = {}
    type_attributes = {}
    types_printed = []
    for type_ in sorted(service_def_types, key=lambda t: t.resolve().enum()):

        out = []

        resolved = type_.resolve()
        namespace_url = resolved.namespace()[1]
        if namespace_url not in standard_type_namespaces:

            if resolved.enum():
                type_description = "enumeration"
            else:
                type_description = "complex type"

            # Look for bases
            interface_bases = []
            if resolved.extension():
                def find(t):
                    for c in t.rawchildren:
                        if c.extension():
                            find(c)
                        if c.ref is not None:
                            interface_bases.append(c.ref[0])

                find(resolved)

            if not interface_bases:
                interface_bases = ['']

            raw_type_name = type_name(type_)

            type_interface_name = normalize_identifier(raw_type_name)

            type_map[raw_type_name] = type_interface_name
            type_seq.append((raw_type_name, type_interface_name,))
            type_attributes[raw_type_name] = {}

            if resolved.enum():
                enum_args = [attr[0].name.replace(' ', '_') for attr in type_.children()]
                #out.append('{0} = Enum("{0}", "{1}")\n'.format(type_interface_name, enum_args))
                out.append('class {0}(Enum):\n'.format(type_interface_name))
                for prop in enum_args:
                    out.append('    {0} = auto()\n'.format(prop))


            else:
                out.append(INTERFACE.format(
                    name=normalize_identifier(type_interface_name),
                    bases=', '.join(interface_bases),
                    docstring=format_docstring(TYPE_INTERFACE_DOCSTRING.format(
                        type=type_description,
                        name=raw_type_name,
                        namespace=namespace_url,
                    )
                    )
                ))
                if type_.children():
                    for attr in type_.children():
                        name = attr[0].name.replace(' ', '_')
                        attr_type_name = type_name(attr[0])
                        type_attributes[raw_type_name][name] = attr_type_name
                        schema_type = schema_type_name(attr[0], deps=type_deps.setdefault(raw_type_name, []))
                        out.append('    {0}: {1} = {2}\n'.format(normalize_identifier(name), schema_type, DEFAULT_VALUE_MAPPING.get(str(schema_type), f'{schema_type}()')))
                else:
                    out.append('    pass\n')

            out.append('\n')

            types_printed.append((raw_type_name, ''.join(out)))
    types_printed = sort_deps(types_printed, type_deps)
    if types_printed:
        type_names, types_printed = zip(*types_printed)
    return type_map, type_seq, type_attributes, list(types_printed), list(type_names)


def get_methods(service_def, type_attributes, remove_input_output_messages, type_names, type_map):
    methods = {}
    for port in service_def.ports:
        for method_name, method_args in port[1]:
            if method_name not in methods:
                method_def = port[0].method(method_name)

                # XXX: This is discards the namespace part
                if method_def.soap.output.body.wrapped:

                    input_message = method_def.soap.input.body.parts[0].element[0]
                    output_message = method_def.soap.output.body.parts[0].element[0]

                    if output_message in type_attributes:
                        if len(type_attributes[output_message]) > 0:
                            response = type_attributes[output_message].values()[0]
                        else:
                            response = "None"
                    else:
                        response = output_message

                    # Remove types used as input/output messages
                    if remove_input_output_messages:
                        def remove_messages(message):
                            for idx, type_name_ in enumerate(type_names):
                                if type_name_ == message:
                                    del type_names[idx]
                                    if input_message in type_map:
                                        del type_map[input_message]

                        remove_messages(input_message)
                        remove_messages(output_message)

                else:
                    response = method_def.soap.output.body.parts[0].element[0]

                methods[method_name] = (response, method_args,)
    return methods


def sort_deps(printed, type_deps):
    """Sort list of complex types based on internal dependencies"""

    printed = list(reversed(printed))

    queue = [item for item in printed if len(type_deps.get(item[0], [])) == 0]
    satisfied = set(queue)
    remaining = [item for item in printed if item not in queue]

    sorted_printed = []

    while queue:
        item = queue.pop()
        item_type_name = item[0]

        sorted_printed.append(item)
        satisfied.add(item_type_name)

        for item in remaining:

            remaining_item_type_name = item[0]

            deps_list = type_deps.get(remaining_item_type_name, [])
            remaining_deps = []
            for dep in deps_list:
                if dep not in satisfied:
                    remaining_deps.append(dep)

            type_deps[remaining_item_type_name] = remaining_deps

            if len(remaining_deps) == 0:
                queue.append(item)
                remaining.remove(item)

    return sorted_printed


def get_service_interface_header(service_def):
    # Main service interface
    return INTERFACE.format(
        name=normalize_identifier(service_def.service.name),
        bases=u"",
        docstring=format_docstring(SERVICE_INTERFACE_DOCSTRING.format(
            service_name=service_def.service.name,
            tns=service_def.wsdl.tns[1],
        )
        )
    )


def get_service_interface(methods, type_map):
    out = []

    for method_name, (method_return_type, arg_list) in sorted(methods.items()):

        method_arg_names = []
        method_arg_details = []
        method_arg_specs = []

        for method_arg_name, arg_detail, more_details in arg_list:
            method_arg_names.append(to_snake_case(method_arg_name))

            # for docstring

            method_modifier_parts = []

            if not arg_detail.required():
                method_modifier_parts.append('optional')
            if arg_detail.nillable:
                method_modifier_parts.append('may be None')

            method_modifiers = ""
            if method_modifier_parts:
                method_modifiers = ' ({0})'.format(', '.join(method_modifier_parts))

            arg_type_name = type_name(arg_detail)

            method_spec = '``{0}`` -- {1}{2}'.format(
                arg_detail.name,
                arg_type_name,
                method_modifiers
            )

            method_arg_details.append(method_spec)

            # for @soap decorator

            schema_type = schema_type_name(arg_detail)
            method_arg_specs.append(schema_type)

        # TODO: Probably not aware of array return types
        if method_return_type not in type_map and method_return_type in SCHEMA_TYPE_MAPPING:
            method_return_type = SCHEMA_TYPE_MAPPING[method_return_type]

        args_str = f''.join(f'{arg_name}: {arg_type}, ' for arg_name, arg_type in zip(method_arg_names, method_arg_specs)).rstrip(', ')

        out.append(f'    def {normalize_identifier(method_name)}(self, {args_str}):')

        out.append(METHOD_DOCSTRING.format(
            args=''.join('\n        ' + arg_det for arg_det in method_arg_details),
            response=method_return_type,
        ))

        out.append(DEFAULT_RETURN.format(args=f''.join(f'{arg_name}, ' for arg_name in method_arg_names).rstrip(', '), method=method_name))

    return ''.join(s + '\n' for s in out)


def get_type_map(type_seq, type_map):
    return TYPE_MAP.format(
        items=',\n'.join(["    '{0}': {1}".format(*k) for k in type_seq if k[0] in type_map])
    )


def generate(client, url=None, standard_type_namespaces=STANDARD_TYPE_NAMESPACES, remove_input_output_messages=True):
    """Given a WSDL URL, return a file that could become your interfaces.py
    """

    printed = []  # list of output to be printed

    for service_def in client.sd:
        printed.append(get_header(url))

        # service_def.types is a list of tuples where the first element is
        # always equal to the second afaik
        service_def_types = (t[0] for t in service_def.types)
        type_map, type_seq, type_attributes, types_printed, type_names = get_printed_types(service_def_types,
                                                                                           standard_type_namespaces)
        printed.extend(types_printed)

        printed.append(get_service_interface_header(service_def))

        methods = get_methods(service_def, type_attributes, remove_input_output_messages, type_names,
                              type_map)  # name -> (response type, list of parameters,)
        printed.append(get_service_interface(methods, type_map))

        type_map_out = get_type_map(type_seq, type_map)
        printed.append(type_map_out)

    return '\n'.join(printed)


def main():
    if len(sys.argv) < 2:
        print('Usage: {0} <url>'.format(sys.argv[0]))
        print('The output will be printed to the console')
        return

    if not '://' in sys.argv[1]:
        sys.argv[1] = 'file://' + os.path.abspath(sys.argv[1])

    if len(sys.argv) == 4:
        client = suds.client.Client(sys.argv[1], username=sys.argv[2], password=sys.argv[3])
    else:
        client = suds.client.Client(sys.argv[1])
    print(generate(client, sys.argv[1]))


if __name__ == '__main__':
    main()


