# -*- coding: utf-8 -*-
import copy
import json
from unittest import TestCase

import pytest
from marshmallow import ValidationError

from lain_sdk.lain_yaml import LainYaml
from lain_sdk.yaml.parser import DOMAIN, LainYamlSchema, ProcType
from lain_sdk.yaml.conf import PRIVATE_REGISTRY

DOMAINS = ['extra.domain1.com', 'extra.domain2.org', DOMAIN]


default_appname = 'hello'
default_build = {'base': 'golang', 'script': ['echo buildscript1', 'echo buildscript2']}
default_release = {'dest_base': 'ubuntu', 'copy': [{'src': 'hello', 'dest': '/usr/bin/hello'}, {'src': 'entry.sh', 'dest': '/entry.sh'}]}
default_test = {'script': ['go test']}
default_web = {'cmd': 'hello', 'port': 80, 'memory': '64m', 'env': ['ENV_A=enva', 'ENV_B=envb'], 'volumes': ['/data', '/var/lib/mysql']}
default_procs = {'web.bar': {'cmd': 'bar', 'port': 8080, 'mountpoint': ['a.com', 'b.cn/xyz']}, 'worker.foo': {'cmd': 'worker', 'memory': '128m'}}
default_meta_version = '1428553798-7142797e64bb7b4d057455ef13de6be156ae81cc'


def copy_if_can(o):
    try:
        return copy.deepcopy(o)
    except TypeError:
        return o


def make_lain_yaml(appname=default_appname,
                   build=default_build,
                   release=default_release,
                   test=default_test,
                   web=default_web,
                   procs=default_procs,
                   meta_version=default_meta_version,
                   registry=PRIVATE_REGISTRY,
                   domains=DOMAINS):
    yaml_dic = locals()
    proc = yaml_dic.pop('procs')
    meta_version = yaml_dic.pop('meta_version')
    registry = yaml_dic.pop('registry')
    domains = yaml_dic.pop('domains')
    for k, v in proc.items():
        yaml_dic[k] = v

    data = {k: copy_if_can(v) for k, v in yaml_dic.items() if v is not None}
    conf = LainYaml(data=data, meta_version=meta_version,
                    registry=registry, domains=domains)
    return conf


def test_crontab():
    schedule = '12 * 28 * 3'
    procs = {'cron.shit': {'cmd': 'job', 'memory': '128m', 'schedule': schedule}}
    conf = make_lain_yaml(procs=procs)
    assert conf.procs['shit'].schedule == schedule
    assert conf.procs['shit'].type is ProcType.cron
    with pytest.raises(ValidationError):
        make_lain_yaml(procs={'cron.shit': {'schedule': '66 * * * *'}})


def test_image():
    registry = 'pornhub.com'
    conf = make_lain_yaml(registry=registry)
    web = conf.procs['web']
    assert web.image == f'{registry}/{default_appname}:release-{default_meta_version}'
    # sometimes we need to override proc image, that's why LainYaml is mutable
    web.image = 'whatever'
    assert web.image == 'whatever'


def test_empty_release():
    conf = make_lain_yaml(release=None)
    assert conf.release.dest_base == ''
    assert tuple(conf.release.copy) == ()
    assert tuple(conf.release.script) == ()


class LainYamlTests(TestCase):

    def test_lain_conf_smoke(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        memory: 64m
                        env:
                            - ENV_A=enva
                            - ENV_B=envb
                        volumes:
                            - /data
                            - /var/lib/mysql
                    web.bar:
                        cmd: bar
                        port: 8080
                        mountpoint:
                            - a.com
                            - b.cn/xyz
                    worker.foo:
                        cmd: worker
                        memory: 128m
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        lc = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert lc.meta_version == meta_version
        web = lc.procs['web']
        assert lc.appname == 'hello'
        assert tuple(web.env) == ('ENV_A=enva', 'ENV_B=envb', )
        assert web.memory == 64000000
        assert web.user == ''
        assert web.workdir == ''
        assert web.port[80].port == 80
        assert web.pod_name == 'hello.web.web'
        foo = lc.procs['foo']
        assert foo.memory == 128000000
        assert tuple(foo.cmd) == ('worker', )
        assert foo.type == ProcType.worker
        bar = lc.procs['bar']
        assert tuple(bar.cmd) == ('bar', )
        assert bar.type == ProcType.web
        assert tuple(bar.mountpoint) == ('a.com', 'b.cn/xyz', )

    def test_lain_conf_port_with_type(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80:tcp
                        env:
                            - ENV_A=enva
                            - ENV_B=envb
                        volumes:
                            - /data
                            - /var/lib/mysql
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ('ENV_A=enva', 'ENV_B=envb')
        assert tuple(hello_conf.procs['web'].volumes) == ('/data', '/var/lib/mysql', '/lain/logs')
        assert tuple(hello_conf.procs['web'].logs) == ()
        assert hello_conf.procs['web'].port[80].port == 80

    def test_lain_conf_without_logs(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                    web:
                        volumes:
                            - /data
                            - /var/lib/mysql
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].logs) == ()

    def test_lain_conf_logs(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                    web:
                        volumes:
                            - /data
                            - /var/lib/mysql
                        logs:
                            - a.log
                            - b.log
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].logs) == ('a.log', 'b.log')
        annotation = json.loads(hello_conf.procs['web'].annotation)
        assert annotation['logs'] == ['a.log', 'b.log']

    def test_lain_conf_port_with_type_but_toomuch(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80:tcp:foo
                        env:
                            - ENV_A=enva
                            - ENV_B=envb
                        volumes:
                            - /data
                            - /var/lib/mysql
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        schema = LainYamlSchema(context={'meta_version': meta_version})
        with pytest.raises(ValidationError) as e:
            schema.load(meta_yaml)
            assert 'port declaration should look like 80:tcp' in str(e)

    def test_lain_conf_port_webtype_without_port_meta(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        env:
                            - ENV_A=enva
                            - ENV_B=envb
                        volumes:
                            - /data
                            - /var/lib/mysql
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ('ENV_A=enva', 'ENV_B=envb')
        assert hello_conf.procs['web'].port[80].port == 80

    def test_lain_conf_proc_name(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script: [go build -o hello]
                    release:
                        dest_base: ubuntu
                        copy:
                            - {dest: /usr/bin/hello, src: hello}
                    test:
                        script: [go test]
                    web.web1:
                        cmd: hello
                        port: 80
                        cpu: 1
                        mountpoint:
                            - a.foo
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        hello_conf.appname == 'hello'
        hello_conf.procs['web1'].cpu == 1
        hello_conf.procs['web1'].port[80].port == 80

    def test_lain_conf_dup_proc_name(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        secret_files:
                          - "hello/hello.tex"
                          -  " /secret"
                          -     /hello
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ()
        assert tuple(hello_conf.procs['web'].volumes) == ('/lain/logs', )
        assert hello_conf.procs['web'].port[80].port == 80
        assert tuple(hello_conf.procs['web'].secret_files) == ('/lain/app/hello/hello.tex', '/lain/app/ /secret', '/hello')

    def test_lain_conf_proc_secret_files_bypass(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        secret_files:
                          - "hello/hello.tex"
                          -  " /secret"
                          -     /hello
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ()
        assert hello_conf.procs['web'].port[80].port == 80
        assert tuple(hello_conf.procs['web'].secret_files) == ('/lain/app/hello/hello.tex', '/lain/app/ /secret', '/hello')

    def test_lain_conf_proc_env_notexists(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ()
        assert hello_conf.procs['web'].port[80].port == 80

    def test_lain_conf_auto_insert_default_mountpoint_for_procname_web(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        memory: 64m
                        env:
                            - ENV_A=enva
                            - ENV_B=envb
                        volumes:
                            - /data
                            - /var/lib/mysql
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert tuple(hello_conf.procs['web'].env) == ('ENV_A=enva', 'ENV_B=envb')
        assert hello_conf.procs['web'].memory == 64000000
        assert hello_conf.procs['web'].port[80].port == 80

    def test_lain_conf_no_mountpoint_for_not_web_type_proc(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    worker:
                        cmd: worker
                        memory: 64m
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.appname == 'hello'
        assert hello_conf.procs['worker'].memory == 64000000
        assert tuple(hello_conf.procs['worker'].mountpoint) == ()

    def test_lain_conf_auto_prefix_default_mountpoint_for_proctype_web(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        memory: 64m
                        mountpoint:
                            - /web
                            - a.foo
                            - c.com/y/z
                    web.admin:
                        cmd: admin
                        port: 80
                        mountpoint:
                            - /admin
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version, domains=DOMAINS)
        assert hello_conf.appname == 'hello'
        left = set(hello_conf.procs['web'].mountpoint)
        right = {'a.foo', 'c.com/y/z',
                 '%s.%s' % (hello_conf.appname, DOMAIN),
                 '%s.lain' % hello_conf.appname,
                 '%s.%s/web' % (hello_conf.appname, DOMAIN),
                 '%s.lain/web' % hello_conf.appname}
        for d in DOMAINS:
            right.add('%s.%s' % (hello_conf.appname, d))
            right.add('%s.%s/web' % (hello_conf.appname, d))

        assert left == right

        left = set(hello_conf.procs['admin'].mountpoint)
        right = {'%s.%s/admin' % (hello_conf.appname, DOMAIN),
                 '%s.lain/admin' % hello_conf.appname}
        for d in DOMAINS:
            right.add('%s.%s/admin' % (hello_conf.appname, d))

        assert left == right

    def test_lain_conf_auto_append_default_mountpoint_for_procname_web(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web:
                        cmd: hello
                        port: 80
                        memory: 64m
                        mountpoint:
                            - a.foo
                            - a.foo/search
                            - b.foo.bar/x
                            - c.com/y/z
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version, domains=DOMAINS)
        assert hello_conf.appname == 'hello'
        left = set(hello_conf.procs['web'].mountpoint)
        right = {'a.foo', 'a.foo/search', 'b.foo.bar/x', 'c.com/y/z', '%s.%s' % (hello_conf.appname, DOMAIN), '%s.lain' % hello_conf.appname}
        right.update(['%s.%s' % (hello_conf.appname, d) for d in DOMAINS])
        assert left == right

    def test_lain_conf_no_mountpoint_for_web_type_but_name_is_not_web_proc_should_raise_exception(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                        script:
                            - echo buildscript1
                            - echo buildscript2
                    release:
                        dest_base: ubuntu
                        copy:
                            - src: hello
                              dest: /usr/bin/hello
                            - src: entry.sh
                              dest: /entry.sh
                    test:
                        script:
                            - go test
                    web.foo:
                        cmd: foo
                        memory: 64m
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        schema = LainYamlSchema(context={'meta_version': meta_version})
        with pytest.raises(Exception) as e:
            schema.load(meta_yaml)
            assert 'proc (type is web but name is not web) should have own mountpoint.' in str(
                e.value)

        meta_version = '1428553798-7142797e64bb7b4d057455ef13de6be156ae81cc'
        schema = LainYamlSchema(context={'meta_version': meta_version})
        with pytest.raises(Exception) as e:
            schema.load(meta_yaml)
            assert 'proc (type is web but name is not web) should have own mountpoint.' in str(
                e.value)

    def test_lain_conf_setuptime_and_killtimeout(self):
        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                    web:
                       cmd: test
                    '''
        meta_version = '1428553798.443334-7142797e64bb7b4d057455ef13de6be156ae81cc'
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.procs['web'].setup_time == 0
        assert hello_conf.procs['web'].kill_timeout == 10

        meta_yaml = '''
                    appname: hello
                    build:
                        base: golang
                    web:
                       cmd: test
                       setup_time: 10
                       kill_timeout: 20
                    '''
        hello_conf = LainYaml(data=meta_yaml, meta_version=meta_version)
        assert hello_conf.procs['web'].setup_time == 10
        assert hello_conf.procs['web'].kill_timeout == 20


def test_build_section_with_old_prepare(old_prepare_yaml):
    meta_version = '123456-abcdefg'
    app_conf = LainYaml(data=old_prepare_yaml, meta_version=meta_version)
    assert app_conf.build.base == 'sunyi00/centos-python:1.0.0'
    assert tuple(app_conf.build.script) == ('pip install -r pip-req.txt', )
    assert tuple(app_conf.build.build_arg) == ('ARG1=arg1', 'ARG2=arg2', )


def test_build_section_with_new_prepare(new_prepare_yaml):
    meta_version = '123456-abcdefg'
    app_conf = LainYaml(data=new_prepare_yaml, meta_version=meta_version)
    assert app_conf.build.base == 'sunyi00/centos-python:1.0.0'
    assert tuple(app_conf.build.script) == ('pip install -r pip-req.txt', )
    assert tuple(app_conf.build.build_arg) == ('ARG1=arg1', 'ARG2=arg2', )
    assert app_conf.build.prepare.version == "0"
    assert tuple(app_conf.build.prepare.keep) == ('node_modules', 'bundle')
    assert tuple(app_conf.build.prepare.script) == ('touch /sbin/modprobe && chmod +x /sbin/modprobe',
                                                    'pip install -r pip-req.txt',
                                                    'rm -rf /lain/app/*',
                                                    'ls -1A | grep -v \'\\bnode_modules\\b\' | grep -v \'\\bbundle\\b\' | xargs rm -rf')


def test_release(release_yaml):
    meta_version = '123456-abcdefg'
    app_conf = LainYaml(data=release_yaml, meta_version=meta_version)
    assert tuple(app_conf.release.copy) == ({'dest': '/usr/bin/hello', 'src': 'hello'}, {'dest': 'hi', 'src': 'hi'})
