import copy
import logging
import re
import yaml

logger = logging.getLogger(__name__)

class ClusterConfig(object):
    """ manage parsing user config.yml to swarm compose file """

    # limits to prevent accidental overprovisioning
    MAX_NODES = 10
    MAX_WORKERS = 128
    MAX_WATCHERS = 4
    MIN_PREFIX = 8
    MAX_PREFIX = 27
    MAX_SHARDS = 32
    MAX_REPLICAS = 3
    MIN_MEMORY = 0.256
    MAX_MEMORY = 32

    # everything has the same logging limits for now
    LOGGING_MAX_SIZE = "50m"
    LOGGING_MAX_FILE = "10"

    def __init__(self, image, node_count=1, app_name=None, worker_count=None, db_shard=None, 
                db_replica=None, db_memory=None, compose_file=None):
        # set container image from base app image
        self.image = image
        self.node_count = node_count
        self.requested_app_name = app_name
        self.requested_worker_count = worker_count
        self.requested_db_shard = db_shard
        self.requested_db_replica = db_replica
        self.requested_db_memory = db_memory
        self.app_workers = 5
        self.app_watchers = 1
        self.app_subnet = "192.0.2.0/27"
        self.app_name = "base"
        # set http/https port to 0 to disable that service
        self.app_http_port = 80
        self.app_https_port = 443
        self.redis_port = 6379
        self.mongos_port = 27017
        self.configsvr_port = 27019
        self.shardsvr_port = 27017
        self.shardsvr_shards = 1
        self.shardsvr_memory = 2.0
        self.shardsvr_replicas = 1
        self.configsvr_memory = 2.0
        self.configsvr_replicas = 1
        self.logging_stdout = False
        self.compose_file = compose_file
        if self.compose_file is None:
            self.compose_file = "/tmp/compose.yml"
        # indexed by service name and contains node label or 0
        self.services = {}

    def import_config(self, configfile):
        """ import/parse and validate config file, raise exception on error """
        logger.info("loading config file: %s", configfile)
        with open(configfile, "r") as f:
            try:
                config = yaml.safe_load(f)
            except yaml.parser.ParserError as e:
                logger.debug(e)
                raise Exception("failed to parse config file")
            # walk through keys, fail if there are any unexpected keys so user knows the config is
            # invalid (this is better than sliently ignoring a configuration user is trying to make)
            for k in config:
                if k == "app":
                    self.add_app(config[k])
                elif k == "database":
                    self.add_database(config[k])
                elif k == "logging":
                    self.add_logging(config[k])
                else:
                    logger.info("unexpected key '%s'", k)
                    raise Exception("invalid config file")

        # override settings with user provided 'requested' state from cli 
        if self.requested_app_name is not None:
            logger.debug("overriding app_name with %s" % self.requested_app_name)
            self.app_name = self.requested_app_name
        if self.requested_worker_count is not None:
            logger.debug("overriding worker_count with %s" % self.requested_worker_count)
            self.app_workers = self.requested_worker_count
            if self.app_workers<1 or self.app_workers > ClusterConfig.MAX_WORKERS:
                raise Exception("invalid worker count '%s', should be between 1 and %s" % (
                    self.app_workers, ClusterConfig.MAX_WORKERS))
        if self.requested_db_shard is not None:
            logger.debug("overriding db shard count with %s" % self.requested_db_shard)
            self.shardsvr_shards = self.requested_db_shard
            if self.shardsvr_shards<1 or self.shardsvr_shards > ClusterConfig.MAX_SHARDS:
                raise Exception("invalid shard count '%s', expected between 1 and %s" % (
                    self.shardsvr_shards, ClusterConfig.MAX_SHARDS))
        if self.requested_db_replica is not None:
            logger.debug("overriding db replica count with %s" % self.requested_db_replica)
            self.shardsvr_replicas = self.requested_db_replica
            self.configsvr_replicas = self.requested_db_replica
            if self.requested_db_replica<1 or self.requested_db_replica>ClusterConfig.MAX_REPLICAS:
                raise Exception("invalid shard replica count %s, expected between 1 and %s"%(
                    self.requested_db_replica, ClusterConfig.MAX_REPLICAS))
        if self.requested_db_memory is not None:
            logger.debug("overriding db memory with %s" % self.requested_db_memory)
            self.shardsvr_memory = self.requested_db_memory
            self.configsvr_memory = self.requested_db_memory
            if self.requested_db_memory<ClusterConfig.MIN_MEMORY \
                or self.requested_db_memory>ClusterConfig.MAX_MEMORY:
                raise Exception("invalid shard memory threshold %s, expected between %sG and %sG"%(
                    self.requested_db_memory, ClusterConfig.MIN_MEMORY, ClusterConfig.MAX_MEMORY))

        # ensure that shardsvr_replicas is <= number of nodes
        if self.shardsvr_replicas > self.node_count:
            logger.debug("(min node) overriding shardsvr replica count to %s", self.node_count)
            self.shardsvr_replicas = self.node_count

        # ensure that configsvr_replicas is <= number of nodes
        if self.configsvr_replicas > self.node_count:
            logger.debug("(min node) overriding configsvr replica count to %s", self.node_count)
            self.configsvr_replicas = self.node_count

    def add_app(self, config):
        """ add app attributes from config """
        logger.debug("adding app config: %s", config)
        for k in config:
            if k == "workers": 
                if type(config[k]) is not int or config[k] > ClusterConfig.MAX_WORKERS:
                    raise Exception("invalid worker count '%s', should be between 1 and %s" % (
                        config[k], ClusterConfig.MAX_WORKERS))
                self.app_workers = config[k]
                logger.debug("setting app_worker count to %s", self.app_workers)
            elif k == "subnet":
                subnet = "%s" % config[k]
                r1 = re.search("^([0-9]+\.){3}[0-9]+/(?P<prefix>[0-9]+)$", subnet)
                if r1 is None:
                    raise Exception("invalid subnet '%s'" % subnet)
                subnet_prefix = int(r1.group("prefix"))
                if subnet_prefix > ClusterConfig.MAX_PREFIX or \
                    subnet_prefix < ClusterConfig.MIN_PREFIX:
                    raise Exception("invalid subnet prefix '%s', expected mask between %s and %s"%(
                        subnet_prefix, ClusterConfig.MIN_PREFIX, ClusterConfig.MAX_PREFIX))
                self.app_subnet = subnet
                logger.debug("setting app_subnet to %s", self.app_subnet)
            elif k == "name":
                self.app_name = config[k]
            elif k == "http_port":
                if type(config[k]) is not int or config[k]<0 or config[k]>0xffff:
                    raise Exception("invalid http port %s, must be between 1 and 65535"%config[k])
                self.app_http_port = config[k]
            elif k == "https_port":
                if type(config[k]) is not int or config[k]<0 or config[k]>0xffff:
                    raise Exception("invalid https port %s, must be between 1 and 65535"%config[k])
                self.app_https_port = config[k]
            else:
                raise Exception("unexpected attribute '%s' for app" % k)

    def add_database(self, config):
        """ add database attributes from config """
        logger.debug("adding database config: %s", config)
        for k in config:
            if k == "shardsvr": 
                self.add_shardsvr(config[k])
            elif k == "configsvr":
                self.add_configsvr(config[k])
            else:
                raise Exception("unexpected attribute '%s' for database" % k)

    def add_shardsvr(self, config):
        """ add shardsvr attributes from config """
        logger.debug("adding shardsvr config: %s", config)
        for k in config:
            if k == "shards": 
                if type(config[k]) is not int or config[k]<1 or config[k]>ClusterConfig.MAX_SHARDS:
                    raise Exception("invalid shard count '%s', expected between 1 and %s" % (
                        config[k], ClusterConfig.MAX_SHARDS))
                self.shardsvr_shards = config[k]
            elif k == "memory":
                if (type(config[k]) is not int and type(config[k]) is not float) or \
                    config[k] <= ClusterConfig.MIN_MEMORY or config[k] > ClusterConfig.MAX_MEMORY:
                    raise Exception("invalid shard memory threshold %s, expected between %G and %sG"%(
                        config[k], ClusterConfig.MIN_MEMORY, ClusterConfig.MAX_MEMORY))
                self.shardsvr_memory = float(config[k])
            elif k == "replicas":
                if type(config[k]) is not int or config[k]<1 or config[k]>ClusterConfig.MAX_REPLICAS:
                    raise Exception("invalid shard replica count %s, expected between 1 and %s"%(
                        config[k], ClusterConfig.MAX_REPLICAS))
                self.shardsvr_replicas = config[k]
            else:
                raise Exception("unexpected attribute '%s' for shardsvr" % k)

    def add_configsvr(self, config):
        """ add configsvr attributes from config """
        logger.debug("adding configsvr config: %s", config)
        for k in config:
            if k == "memory":
                if (type(config[k]) is not int and type(config[k]) is not float) or \
                    config[k] <= 0 or config[k] > ClusterConfig.MAX_MEMORY:
                    raise Exception("invalid configsvr memory threshold %s, expected between 1G and %sG"%(
                        config[k], ClusterConfig.MAX_MEMORY))
                self.configsvr_memory = float(config[k])
            elif k == "replicas":
                if type(config[k]) is not int or config[k]<1 or config[k]>ClusterConfig.MAX_REPLICAS:
                    raise Exception("invalid configsvr replica count %s, expected between 1 and %s"%(
                        config[k], ClusterConfig.MAX_REPLICAS))
                self.configsvr_replicas = config[k]
            else:
                raise Exception("unexpected attribute '%s' for configsvr" % k)

    def add_logging(self, config):
        """ add logging attribute from config """
        logger.debug("adding logging config: %s", config)
        for k in config:
            if k == "stdout":
                if type(config[k]) is bool:
                    self.logging_stdout = config[k]
                elif type(config[k]) is int or type(config[k]) is float:
                    self.logging_stdout = config[k] > 0
                else:
                    raise Exception("invalid logging stdout value %s" % config[k])
            else:
                raise Exception("unexpected attribute '%s' for logging" % k)

    def get_shared_environment(self):
        """ return shared environment list """
        shared_environment = {
            # "HOSTED_PLATFORM": "KUBERNETES",
            "HOSTED_PLATFORM": "SWARM",
            "WEB_PORT": self.app_https_port,
            "REDIS_HOST": "redis",
            "REDIS_PORT": self.redis_port,
            "DB_SHARD_COUNT": self.shardsvr_shards,
            "MONGO_PORT": self.mongos_port,
        }
        # build cfg server string (up to replica count)
        cfg_svr = []
        for i in range(0, self.configsvr_replicas):
            cfg_svr.append("db-cfg-%s:%s" % (i, self.configsvr_port))
        shared_environment["DB_CFG_SRV"] = "cfg/%s" % (",".join(cfg_svr))
        # build shard server config for each shard up to number replica count
        for s in range(0, self.shardsvr_shards):
            rs = []
            for r in range(0, self.shardsvr_replicas):
                rs.append("db-sh-%s-%s:%s" % (s, r, self.shardsvr_port))
            shared_environment["DB_RS_SHARD_%s" % s ] = "sh%s/%s" % (s, ",".join(rs))
        # build comma separated list of mongos routers to set for MONGO_HOST
        mongo_host = []
        for i in range(0, self.node_count):
            mongo_host.append("db-mongos-%s:%s" % (i, self.mongos_port))
        shared_environment["MONGO_HOST"] = ",".join(mongo_host)

        return ["%s=%s" % (k, shared_environment[k]) for k in sorted(shared_environment)]

    def build_compose(self):
        """ build compose file used for kubernetes service """
        tmp_yaml = []

        deployment = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': '', 'labels': []},
                      'spec': {
                          'containers': [
                              {'command': ['/home/app/src/Service/start.sh'],
                               'args': [],
                               'env': [],
                               'image': self.image,
                               'name': '',
                               'ports':[{'containerPort': 443}],
                               'volumeMounts': []
                               }
                          ],
                          'volumes': []
                      }}

        shared_environment = self.get_shared_environment()

        # static logging referenced by each service
        default_logging = {
            "driver": "json-file",
            "options": {
                "mode": "non-blocking",
                "max-buffer-size": "1m",
                "max-size": ClusterConfig.LOGGING_MAX_SIZE,
                "max-file": ClusterConfig.LOGGING_MAX_FILE,
            },
        }

        stdout = "-s" if self.logging_stdout else ""

        # configure webservice (ports are configurable by user)
        svc = 'web'
        self.services["web"] = Service(svc)
        cmd = '/home/app/src/Service/start.sh -r web -l %s' % stdout
        _deployment = copy.deepcopy(deployment)
        _deployment['metadata']['name'] = '%s' % svc
        _deployment['metadata']['labels'] = {'name': '%s' % svc}
        _deployment['spec']['containers'][0]['name'] = '%s' % svc
        _deployment['spec']['hostname'] = '%s' % svc
        _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
        _deployment['spec']['containers'][0]['env'] = [
            {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in shared_environment]
        _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
        _deployment['spec']['volumes'].append(
            {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
        tmp_yaml.append(_deployment)
        _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'web'},
                    'spec': {'selector': {'name': '%s' % svc}, 'ports': []}}
        if self.app_http_port > 0:
            port = {'name': '%s' % self.app_http_port, 'port': self.app_http_port, 'targetPort': self.app_http_port}
            _service["spec"]['ports'].append(port)
        if self.app_https_port > 0:
            port = {'name': '%s' % self.app_https_port, 'port': self.app_https_port, 'targetPort': self.app_https_port}
            _service["spec"]['ports'].append(port)
        tmp_yaml.append(_service)


        # configure redis service (static)
        svc = 'redis'
        self.services["redis"] = Service(svc)
        self.services["redis"].set_service_type("redis", port_number=self.redis_port)
        cmd = '/home/app/src/Service/start.sh -r redis -l %s' % stdout
        _deployment = copy.deepcopy(deployment)
        _deployment['metadata']['name'] = '%s' % svc
        _deployment['metadata']['labels'] = {'name': '%s' % svc}
        _deployment['spec']['containers'][0]['name'] = '%s' % svc
        _deployment['spec']['hostname'] = '%s' % svc
        _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
        _deployment['spec']['containers'][0]['env'] = [
            {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in shared_environment]
        _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
        _deployment['spec']['volumes'].append(
            {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
        tmp_yaml.append(_deployment)
        _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                    'spec': {'selector': {'name': '%s' % svc}, 'ports': [{'name': '%s' % self.redis_port, 'port': self.redis_port, 'targetPort': self.redis_port}]}}
        tmp_yaml.append(_service)


        # configure shard service (multiple shards and replicas)
        for s in range(0, self.shardsvr_shards):
            for r in range(0, self.shardsvr_replicas):
                svc = "db-sh-%s-%s" % (s, r)
                anchor = ((s + r) % self.node_count) + 1
                self.services[svc] = Service(svc, node=anchor, replica="sh%s" % s)
                self.services[svc].set_service_type("db_sh", shard_number=s, replica_number=r, port_number=self.shardsvr_port)
                env = copy.deepcopy(shared_environment)
                env.append("LOCAL_REPLICA=%s" % r)
                env.append("LOCAL_SHARD=%s" % s)
                env.append("LOCAL_PORT=%s" % self.shardsvr_port)
                env.append("DB_MEMORY=%s" % self.shardsvr_memory)
                env.append("DB_ROLE=shardsvr")
                cmd = '/home/app/src/Service/start.sh -r db -l %s' % stdout
                _deployment = copy.deepcopy(deployment)
                _deployment['metadata']['name'] = '%s' % svc
                _deployment['metadata']['labels'] = {'name': '%s' % svc}
                _deployment['spec']['containers'][0]['name'] = '%s' % svc
                _deployment['spec']['hostname'] = '%s' % svc
                _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
                _deployment['spec']['containers'][0]['env'] = [
                    {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in env]
                _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
                _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-data' % svc, 'mountPath': '/home/app/local-data'})
                _deployment['spec']['volumes'].append(
                    {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
                _deployment['spec']['volumes'].append(
                    {'name': '%s-data' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-data' % svc, 'type': 'DirectoryOrCreate'}})
                tmp_yaml.append(_deployment)

                _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                            'spec': {'selector': {'name': '%s' % svc},
                                     'ports': [{'name': '%s' % self.shardsvr_port, 'port': self.shardsvr_port, 'targetPort': self.shardsvr_port}]}}
                tmp_yaml.append(_service)


        # configure configsvr service (replicas only)
        for r in range(0, self.configsvr_replicas):
            svc = "db-cfg-%s" % r
            anchor = (r % self.node_count) + 1
            self.services[svc] = Service(svc, node=anchor, replica="cfg")
            self.services[svc].set_service_type("db_cfg", replica_number=r, port_number=self.configsvr_port)
            cmd = '/home/app/src/Service/start.sh -r db -l %s' % stdout
            env = copy.deepcopy(shared_environment)
            env.append("LOCAL_REPLICA=%s" % r)
            env.append("LOCAL_SHARD=0")
            env.append("LOCAL_PORT=%s" % self.configsvr_port)
            env.append("DB_MEMORY=%s" % self.configsvr_memory)
            env.append("DB_ROLE=configsvr")
            _deployment = copy.deepcopy(deployment)
            _deployment['metadata']['name'] = '%s' % svc
            _deployment['metadata']['labels'] = {'name': '%s' % svc}
            _deployment['spec']['containers'][0]['name'] = '%s' % svc
            _deployment['spec']['hostname'] = '%s' % svc
            _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
            _deployment['spec']['containers'][0]['env'] = [
                {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in env]
            _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
            _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-data' % svc, 'mountPath': '/home/app/local-data'})
            _deployment['spec']['volumes'].append(
                {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
            _deployment['spec']['volumes'].append(
                {'name': '%s-data' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-data' % svc, 'type': 'DirectoryOrCreate'}})
            tmp_yaml.append(_deployment)

            _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                        'spec': {'selector': {'name': '%s' % svc},
                                 'ports': [{'name': '%s' % self.configsvr_port, 'port': self.configsvr_port, 'targetPort': self.configsvr_port}]}}
            tmp_yaml.append(_service)


        # configure router (mongos = main db app will use) pointing to cfg replica
        # will configure a single mongos instance per node with placement policy to tie to node
        for i in range(0, self.node_count):
            svc = "db-mongos-%s" % i
            anchor = (i % self.node_count) + 1
            self.services[svc] = Service(svc, node=anchor, replica="cfg")
            self.services[svc].set_service_type("db", port_number=self.mongos_port)
            cmd = "/home/app/src/Service/start.sh -r db -l %s" % stdout
            env = copy.deepcopy(shared_environment)
            env.append("LOCAL_REPLICA=0")
            env.append("LOCAL_SHARD=0")
            env.append("LOCAL_PORT=%s" % self.mongos_port)
            env.append("DB_MEMORY=%s" % self.configsvr_memory)
            env.append("DB_ROLE=mongos")
            _deployment = copy.deepcopy(deployment)
            _deployment['metadata']['name'] = '%s' % svc
            _deployment['metadata']['labels'] = {'name': '%s' % svc}
            _deployment['spec']['containers'][0]['name'] = '%s' % svc
            _deployment['spec']['hostname'] = '%s' % svc
            _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
            _deployment['spec']['containers'][0]['env'] = [
                {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in env]
            _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
            _deployment['spec']['volumes'].append(
                {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
            tmp_yaml.append(_deployment)

            _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                        'spec': {'selector': {'name': '%s' % svc},
                                 'ports': [{'name': '%s' % self.mongos_port, 'port': self.mongos_port, 'targetPort': self.mongos_port}]}}
            tmp_yaml.append(_service)

        # configure manager, watcher, and workers
        svc = 'mgr'
        self.services["mgr"] = Service("manager")
        cmd = '/home/app/src/Service/start.sh -r mgr -l -c 1 -i 0 %s' % stdout
        _deployment = copy.deepcopy(deployment)
        _deployment['metadata']['name'] = '%s' % svc
        _deployment['metadata']['labels'] = {'name': '%s' % svc}
        _deployment['spec']['containers'][0]['name'] = '%s' % svc
        _deployment['spec']['hostname'] = '%s' % svc
        _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
        _deployment['spec']['containers'][0]['env'] = [
            {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in shared_environment]
        _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
        _deployment['spec']['volumes'].append(
            {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
        tmp_yaml.append(_deployment)

        _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                    'spec': {'selector': {'name': '%s' % svc},
                             'ports': [{'name': '%s' % self.app_https_port, 'port': self.app_https_port, 'targetPort': self.app_https_port}]}}
        tmp_yaml.append(_service)

        # configure multiple watchers (expect just one or two)
        for i in range(0, self.app_watchers):
            svc = "x%s" % i
            self.services[svc] = Service(svc)
            self.services[svc].set_service_type("watcher")
            cmd = '/home/app/src/Service/start.sh -r watcher -l -c 1 -i %s %s' % (i, stdout)
            _deployment = copy.deepcopy(deployment)
            _deployment['metadata']['name'] = '%s' % svc
            _deployment['metadata']['labels'] = {'name': '%s' % svc}
            _deployment['spec']['containers'][0]['name'] = '%s' % svc
            _deployment['spec']['hostname'] = '%s' % svc
            _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
            _deployment['spec']['containers'][0]['env'] = [
                {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in shared_environment]
            _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
            _deployment['spec']['volumes'].append(
                {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
            tmp_yaml.append(_deployment)

            _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                        'spec': {'selector': {'name': '%s' % svc},
                                 'ports': [{'name': '%s' % self.app_https_port, 'port': self.app_https_port, 'targetPort': self.app_https_port}]}}
            tmp_yaml.append(_service)

        # configure multiple workers
        for i in range(0, self.app_workers):
            svc = "w%s" % i
            self.services[svc] = Service(svc)
            self.services[svc].set_service_type("worker")
            cmd = '/home/app/src/Service/start.sh -r worker -l -c 1 -i %s %s' % (i, stdout)
            _deployment = copy.deepcopy(deployment)
            _deployment['metadata']['name'] = '%s' % svc
            _deployment['metadata']['labels'] = {'name': '%s' % svc}
            _deployment['spec']['containers'][0]['name'] = '%s' % svc
            _deployment['spec']['hostname'] = '%s' % svc
            _deployment['spec']['containers'][0]['args'] = cmd.strip().split(' ')[1:]
            _deployment['spec']['containers'][0]['env'] = [
                {'name': item.split('=')[0], 'value': item.split('=')[1]} for item in shared_environment]
            _deployment['spec']['containers'][0]['volumeMounts'].append({'name': '%s-log' % svc, 'mountPath': '/home/app/log'})
            _deployment['spec']['volumes'].append(
                {'name': '%s-log' % svc, 'hostPath': {'path': '/var/lib/docker/volumes/%s-log' % svc, 'type': 'DirectoryOrCreate'}})
            tmp_yaml.append(_deployment)

            _service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': '%s' % svc},
                        'spec': {'selector': {'name': '%s' % svc},
                                 'ports': [{'name': '%s' % self.app_https_port, 'port': self.app_https_port, 'targetPort': self.app_https_port}]}}
            tmp_yaml.append(_service)


        with open(self.compose_file, "w") as f:
            try:
                yaml.safe_dump_all(tmp_yaml, f, default_flow_style=False, allow_unicode=True)
                logger.info("compose file complete: %s", self.compose_file)
            except Exception as e:
                print(e)


class Service(object):

    SERVICE_TYPES = ["web", "redis", "worker", "manager", "watcher", "db", "db_cfg", "db_sh"]
    def __init__(self, name, node=None, replica=None):
        self.name = name
        self.node = node            # node label_id if constrained to a single node
        self.replica = replica      # name of the replica if part of a replication set
        self.service_type = None
        self.replica_number = None
        self.shard_number = None
        self.port_number = None
        if name in Service.SERVICE_TYPES: 
            self.service_type = name

    def set_service_type(self,service_type,shard_number=None,replica_number=None,port_number=None):
        # set service type (which may be same as the name).  For db_sh, can provided the 
        # shard_number.  The supported services:
        #   web
        #   redis
        #   db      (shard router)
        #   db_cfg  (configserver)
        #   db_sh   (shard)
        #   mgr
        #   watcher
        #   worker
        if service_type not in Service.SERVICE_TYPES:
            raise Exception("unsupported service type %s" % service_type)
        self.service_type = service_type
        if shard_number is not None and service_type == "db_sh":
            self.shard_number = shard_number
        if replica_number is not None and self.replica is not None:
            self.replica_number = replica_number
        if port_number is not None:
            self.port_number = port_number

    def __repr__(self):
        return "name: %s, node: %s, replica-name: %s, type: %s, shard: %s, replica: %s, port: %s" % (
            self.name, self.node, self.replica, self.service_type, self.shard_number,
            self.replica_number, self.port_number)
            

