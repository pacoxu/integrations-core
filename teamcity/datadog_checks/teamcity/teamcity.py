# (C) Datadog, Inc. 2014-present
# (C) Paul Kirby <pkirby@matrix-solutions.com> 2014
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
from urllib.parse import urlparse
from collections import namedtuple

from six import PY2

from datadog_checks.base import AgentCheck, ConfigurationError, is_affirmative

from .common import SERVICE_CHECK_STATUS_MAP, BuildConfigCache, construct_event, get_response
from .metrics import build_metric


class TeamCityCheck(AgentCheck):
    __NAMESPACE__ = 'teamcity'

    HTTP_CONFIG_REMAPPER = {
        'ssl_validation': {'name': 'tls_verify'},
        'headers': {'name': 'headers', 'default': {"Accept": "application/json"}},
    }

    def __new__(cls, name, init_config, instances):
        instance = instances[0]

        if is_affirmative(instance.get('use_openmetrics', False)):
            if PY2:
                raise ConfigurationError(
                    "This version of the integration is only available when using py3. "
                    "Check https://docs.datadoghq.com/agent/guide/agent-v6-python-3 "
                    "for more information or use the older style config."
                )
            # TODO: when we drop Python 2 move this import up top
            from .check import TeamCityCheckV2

            return TeamCityCheckV2(name, init_config, instances)
        else:
            return super(TeamCityCheck, cls).__new__(cls)

    def __init__(self, name, init_config, instances):
        super(TeamCityCheck, self).__init__(name, init_config, instances)
        self.build_config_cache = BuildConfigCache()
        self.instance_name = self.instance.get('name')
        self.host = self.instance.get('host_affected') or self.hostname
        self.build_config = self.instance.get('build_configuration')
        self.is_deployment = is_affirmative(self.instance.get('is_deployment', False))
        self.basic_http_auth = is_affirmative(self.instance.get('basic_http_authentication', False))
        self.auth_type = 'httpAuth' if self.basic_http_auth else 'guestAuth'
        self.tags = set(self.instance.get('tags', []))

        parsed_endpoint = urlparse(self.instance.get('server'))
        self.server_url = "{}://{}".format(parsed_endpoint.scheme, parsed_endpoint.netloc)
        self.base_url = "{}/{}".format(self.server_url, self.auth_type)

        instance_tags = [
            'build_config:{}'.format(self.build_config),
            'server:{}'.format(self.server_url),
            'instance_name:{}'.format(self.instance_name),
            'type:deployment' if self.is_deployment else 'type:build',
        ]
        self.tags.update(instance_tags)

    def _send_events(self, new_build):
        self.log.debug(
            "Found new build with id %s (build number: %s), saving and alerting.", new_build['id'], new_build['number']
        )
        self.build_config_cache.set_last_build_id(self.build_config, new_build['id'], new_build['number'])

        teamcity_event = construct_event(self.is_deployment, self.instance_name, self.host, new_build, list(self.tags))
        self.log.trace('Submitting event: %s', teamcity_event)
        self.event(teamcity_event)
        self.service_check('build.status', SERVICE_CHECK_STATUS_MAP.get(new_build['status']), tags=list(self.tags))

    def _initialize(self):
        self.log.debug("Initializing %s", self.instance_name)

        last_build_res = get_response(self, 'last_build', base_url=self.base_url, build_conf=self.build_config)

        last_build_id = last_build_res['build'][0]['id']
        last_build_number = last_build_res['build'][0]['number']
        build_config_id = last_build_res['build'][0]['buildTypeId']

        self.log.debug(
            "Last build id for instance %s is %s (build number:%s).",
            self.instance_name,
            last_build_id,
            last_build_number,
        )
        self.build_config_cache.set_build_config(build_config_id)
        self.build_config_cache.set_last_build_id(build_config_id, last_build_id, last_build_number)

    def _collect_build_stats(self, new_build):
        build_id = new_build['id']
        build_number = new_build['number']
        build_stats = get_response(
            self, 'build_stats', base_url=self.base_url, build_conf=self.build_config, build_id=build_id
        )

        if build_stats:
            for stat_property in build_stats['property']:
                stat_property_name = stat_property['name']
                metric_name, additional_tags, method = build_metric(stat_property_name)
                metric_value = stat_property['value']
                additional_tags.append('build_number:{}'.format(build_number))
                method = getattr(self, method)
                method(metric_name, metric_value, tags=list(self.tags) + additional_tags)

    def _collect_test_results(self, new_build):
        build_id = new_build['id']
        build_number = new_build['number']
        test_results = get_response(self, 'test_occurrences', base_url=self.base_url, build_id=build_id)

        if test_results:
            for test in test_results['testOccurrence']:
                test_status = test['status']
                value = 1 if test_status == 'SUCCESS' else 0
                tags = [
                    'result:{}'.format(test_status.lower()),
                    'build_number:{}'.format(build_number),
                    'build_id:{}'.format(build_id),
                    'test_name:{}'.format(test['name']),
                ]
                self.gauge('test_result', value, tags=list(self.tags) + tags)

    def _collect_build_problems(self, new_build):
        build_id = new_build['id']
        build_number = new_build['number']
        problem_results = get_response(self, 'build_problems', base_url=self.base_url, build_id=build_id)

        if problem_results:
            for problem in problem_results['problemOccurrence']:
                problem_type = problem['type']
                problem_identity = problem['identity']
                tags = [
                    f'problem_type:{problem_type}',
                    f'problem_identity:{problem_identity}',
                    f'build_id:{build_id}',
                    f'build_number:{build_number}',
                ]
                self.service_check('build_problem', AgentCheck.WARNING, tags=list(self.tags) + tags)

    def _collect_all_builds(self):
        all_builds = get_response(self, 'all_builds', base_url=self.base_url)
        for build in all_builds['buildType']:

            self.build_config_cache.set_build_config(build['id'], build['name'])

    def _collect_new_builds(self):
        last_build_ids_dict = self.build_config_cache.get_last_build_id(self.build_config)
        last_build_id = last_build_ids_dict['id']
        new_builds = get_response(
            self, 'new_builds', base_url=self.base_url, build_conf=self.build_config, since_build=last_build_id
        )
        return new_builds

    def _build_collection_object(self):
        collection_config = self.instance.get('monitored_projects_build_configs')
        collection_dict = {}

        for config in collection_config:
            # check if str => project_name
            if isinstance(config, str):
                if not collection_dict[config]:
                    collection_dict[config] = {}
                else:
                    collection_dict
            # check if dict => project and build_configs filters
            # config = {'project': {'include': 'include_something', 'exclude': 'exclude_something'}}
            if isinstance(config, dict):





    def check(self, _):
        if self.instance.get('monitored_projects_build_configs') is not None:
            self._build_collection_object()
        if not self.build_config_cache.get_build_config(self.build_config):
            self._initialize()

        new_builds = self._collect_new_builds()
        if new_builds:
            self.log.debug("New builds found: {}".format(new_builds))
            for build in new_builds['build']:
                self._send_events(build)
                self._collect_build_stats(build)
                self._collect_test_results(build)
                self._collect_build_problems(build)
        else:
            self.log.debug('No new builds found.')
