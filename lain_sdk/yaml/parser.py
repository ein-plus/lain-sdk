# -*- coding: utf-8 -*-
import json
import os
import re
from enum import Enum
from numbers import Number

import humanfriendly
import yaml
from marshmallow import (Schema, ValidationError, fields, post_load, pre_load,
                         validate, validates_schema)
from marshmallow_enum import EnumField

from lain_sdk.util import RichEncoder
from six import itervalues, string_types

from ..mydocker import gen_image_name
from .conf import DOCKER_APP_ROOT, DOMAIN

DEFAULT_SYSTEM_VOLUMES = ('/data/lain/entrypoint:/lain/entrypoint:ro', '/etc/localtime:/etc/localtime:ro')
SOCKET_TYPES = 'tcp udp'
SocketType = Enum('SocketType', SOCKET_TYPES)
PROC_TYPES = 'worker web cron'
ProcType = Enum('ProcType', PROC_TYPES)
VALID_PROC_CLAUSE_PREFIX = set(t.name for t in ProcType)
VALID_PROC_CLAUSE_PREFIX.add('proc')
VALID_PREPARE_VERSION_PATTERN = re.compile(r'^[a-zA-Z0-9]+$')
VALID_ENV_PATTERN = re.compile(r'^\w+=')
INVALID_APPNAMES = ('service', 'resource', 'portal')
INVALID_VOLUMES = {'/', '/lain', DOCKER_APP_ROOT}


def parse_version(s):
    if not isinstance(s, string_types):
        s = str(s)

    if not VALID_PREPARE_VERSION_PATTERN.match(s):
        raise ValidationError(f'version must match {VALID_PREPARE_VERSION_PATTERN}, got {s}')
    return s


def parse_timespan(s):
    if isinstance(s, Number):
        return s
    elif isinstance(s, string_types):
        try:
            return humanfriendly.parse_timespan(s)
        except humanfriendly.InvalidTimespan:
            raise ValidationError(f'failed to parse timespan {s}, you can write int or humanfriendly timespan, see https://humanfriendly.readthedocs.io/en/latest/api.html#humanfriendly.parse_timespan')
    else:
        raise ValidationError(f'failed to parse timespan {s}, you can write int or humanfriendly timespan, see https://humanfriendly.readthedocs.io/en/latest/api.html#humanfriendly.parse_timespan')


def parse_secret_path(path):
    if not os.path.isabs(path):
        return os.path.join(DOCKER_APP_ROOT, path)
    return path


def validate_volume(path):
    if not os.path.isabs(path):
        raise ValidationError(f'volume item must be absolute path, got {path}')
    if path in INVALID_VOLUMES:
        raise ValidationError(f'do not use invalid volumes: {INVALID_VOLUMES}')


def parse_host_port_str(n):
    n = parse_port_str(n)
    if not 9500 <= n <= 10000:
        raise ValidationError(f'host port must be between 9500 and 10000, got {n}')
    return n


def parse_port_str(n):
    try:
        n = int(n)
    except ValueError:
        raise ValidationError(f'port must be a valid int, got {n}')
    if not 0 < n <= 65535:
        raise ValidationError('Port must be 0-65,535')
    return n


def parse_port(p):
    if isinstance(p, int):
        dic = {'type': SocketType.tcp, 'port': p}
    elif isinstance(p, string_types):
        parts = p.split(':')
        if not len(parts) == 2:
            raise ValidationError(f'port declaration should look like 80:tcp, got {p}')
        port, protocol = parts
        try:
            type_ = SocketType[protocol]
        except KeyError:
            raise ValidationError(f'weird port protocol: f{protocol}')
        dic = {'type': type_, 'port': parse_port_str(port)}
    else:
        raise ValidationError(f'port must be int or string_types, got {p}')
    # TODO: fix this weird datastructure
    return {dic['port']: dic}


def parse_memory(s):
    return humanfriendly.parse_size(s) if isinstance(s, string_types) else s


def parse_shared_volumes(s):
    ret = {}
    if isinstance(s, dict):
        global_list = s.get('global', [])
        if isinstance(global_list, list):
            validated_list = []
            for v in global_list:
                v_vector = v.strip().split(":")
                if len(v_vector) == 1:
                    v_src = v_vector[0]
                    v_target = v_vector[0]
                elif len(v_vector) == 2:
                    v_src = v_vector[0]
                    v_target = v_vector[1]
                else:
                    raise ValidationError(f'shared_volumes invalid volume, got {v}')
                if all([os.path.isabs(v_src), os.path.isabs(v_target)]):
                    validated_list.append(":".join([v_src, v_target]))
                else:
                    raise ValidationError(f'shared_volumes volume item must be absolute path, got {v}')
            ret['global'] = validated_list
        else:
            raise ValidationError(f'shared_volumes global list must be a list, got {global_list}')
    else:
        raise ValidationError(f'shared_volumes must be a dict, got {s}')
    return ret


def parse_command(cmd):
    '''
    >>> parse_command('echo whatever')
    ['echo', 'whatever']
    >>> parse_command(['echo', 'whatever'])
    ['echo', 'whatever']
    '''
    if not cmd:
        return cmd
    if isinstance(cmd, string_types):
        return cmd.split()
    elif isinstance(cmd, list):
        return cmd
    raise ValidationError(f'command or entrypoint must be string_types or list, got {cmd}')


def parse_proc_name(proc):
    '''
    >>> parse_proc_name('proc.whatever')
    'whatever'
    >>> parse_proc_name('whatever')
    'whatever'
    >>> parse_proc_name('a.b.c')
    Traceback (most recent call last):
        ...
    marshmallow.exceptions.ValidationError: too many dots in proc name: a.b.c
    '''
    parts = proc.split('.')
    length = len(parts)
    if length == 1:
        return parts[0]
    if length == 2:
        return parts[-1]
    raise ValidationError(f'too many dots in proc name: {proc}')


def parse_copy(stuff):
    '''
    >>> parse_copy('/path')
    {'src': '/path', 'dest': '/path'}
    >>> parse_copy({'src': '/path'})
    {'src': '/path', 'dest': '/path'}
    >>> parse_copy({'src': '/path', 'dest': '/another'})
    {'src': '/path', 'dest': '/another'}
    '''
    if isinstance(stuff, string_types):
        return {'src': stuff, 'dest': stuff}
    elif isinstance(stuff, dict):
        if 'src' not in stuff:
            raise ValidationError('if copy clause is a dict, it must contain src')
        if 'dest' not in stuff:
            stuff['dest'] = stuff['src']

        return stuff
    raise ValidationError(f'copy clause must be string_types or dict, got {stuff}')


class PrepareSchema(Schema):
    version = fields.Function(deserialize=parse_version, missing='0')
    script = fields.List(fields.Str(), missing=[])
    keep = fields.List(fields.Str(), missing=[])

    @post_load
    def finalize(self, data):
        keep_script = ''
        for k in data['keep']:
            keep_script += '| grep -v \'\\b%s\\b\' ' % k

        clean_script = "ls -1A %s| xargs rm -rf" % keep_script
        data['script'].append(clean_script)
        return data


class BuildSchema(Schema):
    base = fields.Str(required=True)
    prepare = fields.Nested(PrepareSchema, missing=PrepareSchema().load({}))
    script = fields.List(fields.Str(), missing=[])
    build_arg = fields.List(fields.Str(), missing=[])


class ReleaseSchema(Schema):
    script = fields.List(fields.Str(), missing=[])
    dest_base = fields.Str(missing='')
    copy = fields.List(fields.Function(deserialize=parse_copy), missing=[])


class TestSchema(Schema):
    script = fields.List(fields.Str(), missing=[])


class ProcSchema(Schema):
    name = fields.Function(deserialize=parse_proc_name, required=True)
    type_ = EnumField(ProcType, missing=ProcType.worker, data_key='type', attribute='type')
    image = fields.Str(missing='')
    entrypoint = fields.Function(deserialize=parse_command, missing=[])
    cmd = fields.Function(deserialize=parse_command)
    schedule = fields.Str(missing='')
    num_instances = fields.Int(missing=1)
    cpu = fields.Int(missing=0)
    memory = fields.Function(deserialize=parse_memory, missing=parse_memory('32m'))
    port = fields.Function(deserialize=parse_port, missing={})
    mountpoint = fields.List(fields.Str(), missing=[])
    user = fields.Str(missing='')
    workdir = fields.Str(missing='')
    env = fields.List(fields.Str(validate=validate.Regexp(VALID_ENV_PATTERN)), missing=[])
    volumes = fields.List(fields.Str(validate=validate_volume), missing=[])
    persistent_dirs = fields.List(fields.Str(validate=validate_volume), missing=[])
    shared_volumes = fields.Function(deserialize=parse_shared_volumes, missing={})
    logs = fields.List(fields.Str(validate=lambda s: not os.path.isabs(s)), missing=[])
    secret_files = fields.List(fields.Function(deserialize=parse_secret_path), missing=[])
    setup_time = fields.Function(deserialize=parse_timespan, missing=0)
    kill_timeout = fields.Function(deserialize=parse_timespan, missing=10)

    @validates_schema
    def validate(self, data):
        # cron procs are special, some fields are necessary, some must not be
        # present
        if data['type'] is ProcType.cron:
            if not data.get('schedule'):
                raise ValidationError(f'when type is cron, must provide schedule, got {data}')

    @post_load
    def finalize(self, data):
        free_volume = '/lain/logs'
        volumes = data['volumes']
        volumes.extend(data.pop('persistent_dirs', []))
        if free_volume not in volumes:
            volumes.append('/lain/logs')

        if data['type'] == ProcType.web and not data.get('port'):
            data['port'] = {80: {'type': SocketType.tcp, 'port': 80}}

        # TODO: confirm functionality
        data['cloud_volumes'] = {}
        # TODO: move functionality to deployd
        data['system_volumes'] = DEFAULT_SYSTEM_VOLUMES
        return data


class LainYamlSchema(Schema):
    appname = fields.Str(required=True, validate=validate.NoneOf(INVALID_APPNAMES))
    build = fields.Nested(BuildSchema)
    release = fields.Nested(ReleaseSchema, missing=ReleaseSchema().load({}))
    test = fields.Nested(TestSchema, missing=TestSchema().load({}))
    # this field is populated during pre_load
    # this field cannot be written directly in lain.yaml
    procs = fields.Dict(values=fields.Nested(ProcSchema),
                        required=True,
                        error_messages={'required': 'missing proc definition'})

    @staticmethod
    def tell_proc_info(key):
        '''
        >>> LainYamlSchema.tell_proc_info('web')
        ('web', 'web')
        >>> LainYamlSchema.tell_proc_info('web.shit')
        ('web', 'shit')
        >>> LainYamlSchema.tell_proc_info('worker.shit')
        ('worker', 'shit')
        >>> LainYamlSchema.tell_proc_info('proc.web')
        (None, 'web')
        >>> LainYamlSchema.tell_proc_info('proc.')
        Traceback (most recent call last):
            ...
        marshmallow.exceptions.ValidationError: bad split: proc.
        >>> LainYamlSchema.tell_proc_info('whatever')
        (None, None)
        '''
        if '.' not in key:
            if key in VALID_PROC_CLAUSE_PREFIX:
                return key, key
            return None, None
        parts = key.split('.')
        if not all(parts):
            raise ValidationError(f'bad split: {key}')
        length = len(parts)
        if length > 2:
            raise ValidationError(f'weird proc key {key}')
        type_, name = parts
        if type_ not in VALID_PROC_CLAUSE_PREFIX:
            raise ValidationError(f'proc key prefix must be in {VALID_PROC_CLAUSE_PREFIX}, got {key}')
        if type_ == 'proc':
            return None, name
        return type_, name

    @pre_load
    def preprocess(self, data):
        if not isinstance(data, dict):
            data = yaml.load(data)

        if 'build' not in data:
            data['build'] = {
                'base': 'scratch',
                'script': ['echo DUMMY']
            }

        # collect all proc clauses and put them in a single dict
        if 'procs' in data:
            raise ValidationError('must not write procs in lain.yaml, its generated by program')
        procs = {}
        for key, clause in list(data.items()):
            type_, name = self.tell_proc_info(key)
            if not name:
                continue
            clause['name'] = name
            if not clause.get('type'):
                clause['type'] = type_

            if not clause['type']:
                raise ValidationError(f'cannot infer proc type of {key}:{clause}')
            if name in procs:
                raise ValidationError(f'duplicate proc name: {name}')
            procs[name] = data.pop(key)

        data['procs'] = procs
        return data

    @staticmethod
    def complete_mountpoint(mountpoint, domains, main_entrance=False):
        '''
        >>> LainYamlSchema.complete_mountpoint(['/foo', 'pornhub.com/bar'], ['baidu.com', 'google.com'])
        ['pornhub.com/bar', 'baidu.com/foo', 'google.com/foo']
        >>> LainYamlSchema.complete_mountpoint(['/foo', 'pornhub.com/bar'], ['baidu.com', 'google.com'], main_entrance=True)
        ['pornhub.com/bar', 'baidu.com/foo', 'google.com/foo', 'baidu.com', 'google.com']
        '''
        for path in mountpoint[:]:
            if path.startswith('/'):
                # we want full urls, not path
                full_paths = [f'{domain}{path}' for domain in domains]
                mountpoint.extend(full_paths)

        if main_entrance:
            mountpoint.extend(domains)

        return [path for path in mountpoint if not path.startswith('/')]

    @post_load
    def finalize(self, data):
        appname = data['appname']
        meta_version = data['meta_version'] = self.context['meta_version']
        default_image = gen_image_name(appname, 'release',
                                       meta_version=meta_version,
                                       registry=self.context['registry'])
        for proc in itervalues(data['procs']):
            if not proc['image']:
                proc['image'] = default_image

            type_ = proc['type']
            name = proc['name']
            proc['pod_name'] = f'{appname}.{type_.name}.{name}'
            if type_ is ProcType.web:
                is_main = name == 'web'
                mountpoint = proc['mountpoint']
                domains = ['%s.%s' % (appname, domain) for domain in self.context.get('domains', [DOMAIN])]
                domains.append('%s.lain' % (appname, ))
                if name == 'web' and not mountpoint:
                    proc['mountpoint'] = domains
                elif not mountpoint:
                    raise ValidationError(f'you must define mountpoint for proc {name}, only proc named web will have free mountpoints')
                else:
                    proc['mountpoint'] = self.complete_mountpoint(mountpoint, domains, main_entrance=is_main)

            proc['annotation'] = json.dumps(proc, cls=RichEncoder)

        return data


def get_app_domain(appname):
    try:
        app_domain_list = appname.split('.')
        app_domain_list.reverse()
        app_domain = '.'.join(app_domain_list)
    except Exception:
        app_domain = appname
    return app_domain
