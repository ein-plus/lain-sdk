import docker
from requests.exceptions import HTTPError
import yaml
import os
import io
import tarfile
from docker_registry_client import DockerRegistryClient


target_directory = 'sample_lain_yaml'
try:
    os.mkdir(target_directory)
except FileExistsError:
    pass
client = docker.from_env(version='auto')
registry_host = 'registry.lain.ein.plus'
registry = DockerRegistryClient(f'http://{registry_host}')

repos = registry.repositories()
print(repos)
for repo in repos.values():
    try:
        tags = repo.tags()
    except HTTPError:
        continue
    if not tags:
        continue
    try:
        latest_meta_tag = max(t for t in tags if t.startswith('meta-'))
    except ValueError:
        continue
    image_name = f'{registry_host}/{repo.name}:{latest_meta_tag}'
    client.images.pull(image_name)
    container = client.containers.create(image_name, command='whatever')
    response, _ = container.get_archive('/lain.yaml')
    bytes_ = b''.join(b for b in response)
    tar = tarfile.open(fileobj=io.BytesIO(bytes_))
    content = tar.extractfile('lain.yaml').read()
    meta = yaml.safe_load(content)
    container.remove()
    fname = f"{target_directory}/{meta['appname']}-lain.yaml"
    with open(fname, 'wb') as f:
        f.write(content)

    print(f'create {fname}')
