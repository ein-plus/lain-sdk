# -*- coding: utf-8 -*-
import collections
import os
import re
import subprocess
import tempfile
import time
from functools import partial
from subprocess import call

from box import Box

from . import mydocker
from .util import error, file_parent_dir, get_cfd, info, mkdir_p, rm, warn
from .yaml.conf import DOCKER_APP_ROOT, DOMAIN, PRIVATE_REGISTRY, user_config
from .yaml.parser import LainYamlSchema

DOMAIN_KEY = user_config.domain_key
TEMPLATE_DIR = os.path.join(get_cfd(__file__), 'yaml/templates')


class TolerantBox(Box):

    @property
    def copy(self):
        return self['copy']


class LainYaml(object):
    """
    Parser of lain.yaml and API to build images from lain.yaml

    Must set self.yaml_path if you need to build images or access extra information like image names
    either pass in during __init__, or pass in through init_act(yaml_path)
    """

    yaml_path = ''

    def __init__(self, data=None, meta_version=None, domains=[DOMAIN],
                 registry=PRIVATE_REGISTRY, lain_yaml_path=None, ignore_prepare=False):
        # lazy initialization, if only need to parse, on need to init fields
        # related to actions
        self.act = False
        if lain_yaml_path:
            if not meta_version:
                meta_version = self.calculate_meta_version(lain_yaml_path)

            self.yaml_path = lain_yaml_path = os.path.abspath(lain_yaml_path)
            self.load(open(lain_yaml_path).read(), meta_version=meta_version, domains=domains, registry=registry)
            self.init_act(ignore_prepare=ignore_prepare)
        elif data:
            self.load(data, meta_version=meta_version, domains=domains, registry=registry)

    def load(self, data, meta_version=None, domains=None, registry=None):
        '''load lain.yaml into this object, can take either yaml string or dict'''
        schema = LainYamlSchema(context={'meta_version': meta_version,
                                         'domains': domains,
                                         'registry': registry})
        self.schema = schema
        loaded = schema.load(data)
        box = TolerantBox(loaded,
                          conversion_box=False,
                          default_box=True,
                          default_box_attr=None)
        self.box = box
        for k in loaded.keys():
            setattr(self, k, getattr(box, k))

    @staticmethod
    def calculate_meta_version(repo_dir, sha1=''):
        if not os.path.isdir(repo_dir):
            repo_dir = os.path.dirname(repo_dir)

        if sha1:
            git_cmd = ['git', 'log', '-1', sha1, '--pretty=format:%ct-%H']
        else:
            git_cmd = ['git', 'log', '-1', '--pretty=format:%ct-%H']

        try:
            commit_hash = subprocess.check_output(
                git_cmd, cwd=repo_dir, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            warn('Error getting cd Git commit hash: {}'.format(e.output))
            return None

        return commit_hash.decode()

    def init_act(self, ignore_prepare=False):
        if self.act is True:
            return

        if self.yaml_path is None:
            raise Exception(
                'self.yaml_path not set, can not perform action, only fields defined in lain.yaml is accessible')

        self.ctx = file_parent_dir(self.yaml_path)
        self.workdir = DOCKER_APP_ROOT + '/'  # '/' is need for COPY in Dockefile

        self.ignore = ['.git', '.vagrant']

        self.gen_name = partial(mydocker.gen_image_name, appname=self.appname, meta_version=self.calculate_meta_version(self.ctx))

        phases = ('prepare', 'build', 'release', 'test', 'meta')
        self.img_names = {phase: self.gen_name(
            phase=phase) for phase in phases}
        if ignore_prepare:
            shared_prepare_image_name = None
        else:
            shared_prepare_image_name = self.ensure_proper_shared_image()
        if shared_prepare_image_name is None:
            self.img_names['prepare'] = self.gen_prepare_shared_image_name()
        else:
            self.img_names['prepare'] = shared_prepare_image_name

        j2temps = {
            'prepare': 'build_dockerfile.j2',
            'build': 'build_dockerfile.j2',
            'release': 'release_dockerfile.j2',
            'test': 'build_dockerfile.j2',
            'meta': 'meta_dockerfile.j2'
        }
        self.img_temps = {phase: self.load_template(
            j2temps[phase]) for phase in phases}

        self.img_builders = {
            phase: partial(mydocker.build, name=self.img_names[phase], ignore=self.ignore, template=self.img_temps[phase])
            for phase in phases
        }

        self.prepare_updater = partial(
            mydocker.build, ignore=self.ignore, template=self.load_template('build_dockerfile.j2'))

        self.act = True

    @staticmethod
    def load_template(filename):
        with open(os.path.join(TEMPLATE_DIR, filename)) as f:
            return f.read()

    def _get_prepare_shared_image_names(self, remote=True):
        prepare_version = self.build.prepare.version
        registry = PRIVATE_REGISTRY

        if not registry:
            error("Please set private_docker_registry config first!")
            error(
                "Use 'lain config save-global private_docker_registry ${registry_domain}'")
            exit(1)

        image_prefix = "{}/{}".format(registry, self.appname)
        if remote:
            # 预设就是 prepare image 存在 PRIVATE_REGISTRY
            tags = mydocker.get_tag_list_in_registry(registry, self.appname)
        else:
            tags = mydocker.get_tag_list_in_docker_daemon(
                registry, self.appname)
        prepare_shared_images = {}
        VALID_TAG_PATERN = re.compile(
            r"^prepare-{}-(?P<timestamp>\d+)$".format(prepare_version))
        for tag in tags:
            matched = VALID_TAG_PATERN.match(tag)
            if matched:
                _timestamp = int(matched.group('timestamp'))
                prepare_shared_images[_timestamp] = "{}:{}".format(
                    image_prefix, tag)
        ordered_images = collections.OrderedDict(sorted(
            prepare_shared_images.items(), reverse=True))
        return ordered_images

    def gen_prepare_shared_image_name(self):
        # 如果没有可用的 shared prepare image ，则需要创建一个新的，这里提供新
        # image 的名字
        prepare_version = self.build.prepare.version
        registry = PRIVATE_REGISTRY
        image_prefix = "{}/{}".format(registry, self.appname)
        timestamp = int(time.time())
        return "{}:prepare-{}-{}".format(
            image_prefix, prepare_version, timestamp
        )

    def ensure_proper_shared_image(self):
        # 在 registry 以及本地寻找合适可用的 shared prepare
        # 如果找到则保证本地和 registry 里此 image 均可用
        # 上述行为成功后返回此 prepare image name
        # 两处都没有合适的 image name 则返回 None
        remote_images = self._get_prepare_shared_image_names(True).items()
        if remote_images:
            remote_latest = list(remote_images)[0]
        else:
            remote_latest = None

        local_images = self._get_prepare_shared_image_names(False).items()
        if local_images:
            local_latest = list(local_images)[0]
        else:
            local_latest = None

        if remote_latest and local_latest:
            info("found shared prepare image at remote and local, sync ...")
            if remote_latest[0] > local_latest[0]:
                if mydocker.pull(remote_latest[1]) != 0:
                    error("FAILED: docker pull {}".format(remote_latest[1]))
                    raise Exception("remote prepare fetching failed.")
                return remote_latest[1]
            elif remote_latest[0] < local_latest[0]:
                if mydocker.push(local_latest[1]) != 0:
                    warn("FAILED: docker push {}".format(local_latest[1]))
                return local_latest[1]
            else:
                return local_latest[1]
        if remote_latest and local_latest is None:
            info("found shared prepare image at remote.")
            if mydocker.pull(remote_latest[1]) != 0:
                error("FAILED: docker pull {}".format(remote_latest[1]))
                raise Exception("remote prepare fetching failed.")
            return remote_latest[1]
        if remote_latest is None and local_latest:
            info("found shared prepare image at local.")
            if mydocker.push(local_latest[1]) != 0:
                warn("FAILED: docker push {}".format(local_latest[1]))
            return local_latest[1]
        if remote_latest is None and local_latest is None:
            warn(
                "found no proper shared prepare image neither at local nor remote, rebuild ...")
            return None

    def build_prepare(self):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()

        if (not mydocker.exist(self.img_names['prepare'])):
            params = {
                'base': self.build.base,
                'workdir': self.workdir,
                'copy_list': ['.'],
                'scripts': self.build.prepare.script,
            }
            name = self.img_builders['prepare'](
                context=self.ctx, params=params, build_args=[])
            if name is None:
                return (False, None)
            if mydocker.push(self.img_names['prepare']) != 0:
                warn("FAILED: docker push {}".format(
                    self.img_names['prepare']))
            return (True, name)
        else:
            return (True, self.img_names['prepare'])

    def update_prepare(self):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()

        # no existed shared prepare
        if (not mydocker.exist(self.img_names['prepare'])):
            params = {
                'base': self.build.base,
                'workdir': self.workdir,
                'copy_list': ['.'],
                'scripts': self.build.prepare.script,
            }
            name = self.img_builders['prepare'](
                context=self.ctx, params=params, build_args=[])
            if name is None:
                return (False, None)
            if mydocker.push(self.img_names['prepare']) != 0:
                warn("FAILED: docker push {}".format(
                    self.img_names['prepare']))
            return (True, name)
        else:
            params = {
                'base': self.img_names['prepare'],
                'workdir': self.workdir,
                'copy_list': ['.'],
                'scripts': self.build.prepare.script,
            }
            name = self.prepare_updater(
                name=self.gen_prepare_shared_image_name(),
                context=self.ctx, params=params, build_args=[])
            if name is None:
                return (False, None)
            if mydocker.push(name) != 0:
                warn("FAILED: docker push {}".format(name))

            return (True, name)

    def build_base(self, use_prepare=False):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()

        # image prepare
        if not (mydocker.exist(self.img_names['prepare']) and use_prepare):
            if not self.build_prepare()[0]:
                return (False, None)

        # image build
        params = {
            'base': self.img_names['prepare'],
            'workdir': self.workdir,
            'copy_list': ['.'],
            'scripts': self.build.script,
            'build_args': [arg.split('=')[0] for arg in self.build.build_arg]
        }
        name = self.img_builders['build'](context=self.ctx, params=params, build_args=self.build.build_arg)
        if name is None:
            return (False, None)
        return (True, name)

    def build_release(self, use_prepare=False, use_build=False):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()
        if (not use_build) and (not self.build_base(use_prepare)[0]):
            return (False, None)

        if self.release.script != []:
            params = {
                'base': self.img_names['build'],
                'workdir': self.workdir,
                'copy_list': [],
                'scripts': self.release.script,
                'build_args': [arg.split('=')[0] for arg in self.build.build_arg]
            }
            inter_name = self.gen_name(phase='script_inter')
            script_inter_name = mydocker.build(
                inter_name, self.ctx, self.ignore, self.img_temps['build'], params, self.build.build_arg)
            if script_inter_name is None:
                return (False, None)
        else:
            script_inter_name = self.img_names['build']

        if self.release.dest_base == '':
            mydocker.tag(script_inter_name, self.img_names['release'])
            return (True, self.img_names['release'])

        copy_dest = '/lain/release'

        def to_dest(f):
            return copy_dest + os.path.join(DOCKER_APP_ROOT, f)

        src_dest = [(
            x.get('src', x), to_dest(x.get('dest', x))) for x in self.release.copy
        ]
        copy_scripts = []
        release_tar = 'release.tar'
        for src, dest in src_dest:
            copy_scripts.append(' '.join(['mkdir', '-p', os.path.dirname(dest)]))
            copy_scripts.append(' '.join(['cp', '-r', src, dest]))
        tar_script = ["tar -cf {} -C {} .".format(release_tar, copy_dest)]
        params = {
            'base': script_inter_name,
            'workdir': self.workdir,
            'copy_list': [],
            'scripts': copy_scripts + tar_script
        }
        inter_name = self.gen_name(phase='copy_inter')
        copy_inter_name = mydocker.build(
            inter_name, self.ctx, self.ignore, self.img_temps['build'], params, [])
        if script_inter_name != self.img_names['build']:
            mydocker.remove_image(script_inter_name)
        if copy_inter_name is None:
            return (False, None)

        try:
            host_release_tar = tempfile.NamedTemporaryFile(dir='/tmp', delete=False).name
            untar = tempfile.mkdtemp(dir='/tmp')

            mydocker.copy_to_host(copy_inter_name, os.path.join(
                DOCKER_APP_ROOT, release_tar), host_release_tar)
            mydocker.remove_image(copy_inter_name)

            mkdir_p(untar)
            call(['tar', '-xf', host_release_tar, '-C', untar])

            params = {
                'base': self.release.dest_base,
                'workdir': self.workdir,
                'copy_list': ['.'],
            }
            name = self.img_builders['release'](context=untar, params=params, build_args=[])
        except Exception:
            name = None
        finally:
            delete = (host_release_tar, untar)
            for f in delete:
                if os.path.exists(f):
                    rm(f)

        if name is None:
            return (False, None)
        return (True, name)

    def build_test(self):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()
        if not self.build_base(use_prepare=True)[0]:
            return (False, None)

        params = {
            'base': self.img_names['build'],
            'workdir': self.workdir,
            'copy_list': [],
            'scripts': self.test.script
        }
        test_name = self.img_builders['test'](context=self.ctx, params=params, build_args=[])

        if test_name is None:
            error("Tests Fail")
            return (False, None)
        else:
            info("Tests Passed")
            return (True, test_name)

    def build_meta(self):
        """
        :return: (True, image_name) or (False, None)
        """
        self.init_act()
        params = {
            'base': 'scratch',
            'lain_yaml_path': os.path.basename(self.yaml_path),
        }
        name = self.img_builders['meta'](context=self.ctx, params=params, build_args=[])
        if name is None:
            return (False, None)
        return (True, name)

    def tag_meta_version(self, name, sha1=''):
        tagged = '%s/%s' % (PRIVATE_REGISTRY, name)
        mydocker.tag(name, tagged)
        return tagged
