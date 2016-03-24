#!/usr/bin/python2.7
import argparse
import sys
import os
import logging
import json
import re
import httplib
from cloudfoundry_client.calls import ConnectionError, InvalidStatusCode
from cloudfoundry_client.client import CloudFoundryClient


__all__ = ['main', 'build_client_from_configuration']

_logger = logging.getLogger(__name__)


def _read_value_from_user(prompt, error_message=None, validator=None, default=''):
    while True:
        sys.stdout.write('%s : ' % prompt)
        sys.stdout.flush()
        answer_value = sys.stdin.readline().rstrip(' \r\n')
        if len(answer_value) == 0:
            answer_value = default
        if len(answer_value) > 0 and (validator is None or validator(answer_value)):
            return answer_value
        else:
            if error_message is None:
                sys.stderr.write('\"%s\": invalid value\n' % answer_value)
            else:
                sys.stderr.write('\"%s\": %s\n' % (answer_value, error_message))


def build_client_from_configuration():
    dir_conf = os.path.join(os.path.expanduser('~'))
    if not os.path.isdir(dir_conf):
        if os.path.exists(dir_conf):
            raise IOError('%s exists but is not a directory')
        os.mkdir(dir_conf)
    config_file = os.path.join(dir_conf, '.cf_client_python.json')
    if not os.path.isfile(config_file):
        target_endpoint = _read_value_from_user('Please enter a target endpoint',
                                                'Url must starts with http:// or https://',
                                                lambda s: s.startswith('http://') or s.startswith('https://'))
        skip_ssl_verification = _read_value_from_user('Skip ssl verification (true/false) [false]',
                                                      'Enter either true or false',
                                                      lambda s: s == 'true' or s == 'false', 'false')
        login = _read_value_from_user('Please enter your login')
        password = _read_value_from_user('Please enter your password')
        client = CloudFoundryClient(target_endpoint, skip_verification=(skip_ssl_verification == 'true'))
        client.credentials_manager.init_with_credentials(login, password)
        with open(config_file, 'w') as f:
            f.write(json.dumps(dict(target_endpoint=target_endpoint,
                                    skip_ssl_verification=(skip_ssl_verification == 'true'),
                                    access_token=client.credentials_manager.access_token(),
                                    refresh_token=client.credentials_manager.refresh_token()), indent=2))
        return client
    else:
        try:
            with open(config_file, 'r') as f:

                configuration = json.load(f)
                client = CloudFoundryClient(configuration['target_endpoint'],
                                            skip_verification=configuration['skip_ssl_verification'])
                client.credentials_manager.init_with_tokens(configuration['access_token'],
                                                            configuration['refresh_token'])
                return client
        except Exception, ex:
            if type(ex) == ConnectionError:
                raise
            else:
                sys.stderr.write('Could not restore configuration. Cleaning and recreating\n')
                os.remove(config_file)
                build_client_from_configuration()


def is_guid(s):
    return re.match('[\d|a-z]{8}-[\d|a-z]{4}-[\d|a-z]{4}-[\d|a-z]{4}-[\d|a-z]{12}', s.lower()) is not None


def log_recent(client, application_guid):
    for message in client.loggregator.get_recent(application_guid):
        _logger.info(message.message)


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(message)s')
    client = build_client_from_configuration()
    parser = argparse.ArgumentParser(add_help=True)
    subparsers = parser.add_subparsers(help='commands', dest='action')
    commands = dict()
    commands['organization'] = dict(list=(), name='name', allow_retrieve_by_name=True, allow_creation=True,
                                    allow_deletion=True)
    commands['space'] = dict(list=('organization_guid',), name='name', allow_retrieve_by_name=True, allow_creation=True,
                             allow_deletion=True)
    commands['application'] = dict(list=('organization_guid', 'space_guid',), name='name',
                                   allow_retrieve_by_name=True, allow_creation=True, allow_deletion=True)
    commands['service'] = dict(list=('service_broker_guid',), name='label', allow_retrieve_by_name=True,
                               allow_creation=True,
                               allow_deletion=True)
    commands['service_plan'] = dict(list=('service_guid', 'service_instance_guid', 'service_broker_guid'), name='name',
                                    allow_retrieve_by_name=False, allow_creation=False, allow_deletion=False)
    commands['service_instance'] = dict(list=('organization_guid', 'space_guid', 'service_plan_guid'), name='name',
                                        allow_retrieve_by_name=False, allow_creation=True, allow_deletion=True)
    commands['service_binding'] = dict(list=('app_guid', 'service_instance_guid'), name=None,
                                       allow_retrieve_by_name=False, allow_creation=True, allow_deletion=True)
    commands['service_broker'] = dict(list=('name', 'space_guid'), name='name',
                                      allow_retrieve_by_name=True, allow_creation=True, allow_deletion=True)
    application_commands = dict(recent_logs=('get_recent_logs', 'Recent Logs',),
                                env=('get_env', 'Environment',),
                                routes=('get_routes', 'Routes',),
                                instances=('get_routes', 'Instances',),
                                stats=('get_stats', 'Stats',),
                                start=('start', 'Start application',),
                                stop=('stop', 'Stop application',))
    for command, command_description in application_commands.items():
        command_parser = subparsers.add_parser(command, help=command_description[1])
        command_parser.add_argument('id', metavar='ids', type=str, nargs=1,
                                    help='The id. Can be UUID or name (first found then)')
    for domain, command_description in commands.items():
        list_parser = subparsers.add_parser('list_%ss' % domain, help='List %ss' % domain)
        for filter_parameter in command_description['list']:
            list_parser.add_argument('-%s' % filter_parameter, action='store', dest=filter_parameter, type=str,
                                     default=None, help='Filter with %s' % filter_parameter)
        get_parser = subparsers.add_parser('get_%s' % domain, help='Get a %s' % domain)
        get_parser.add_argument('id', metavar='ids', type=str, nargs=1,
                                help='The id. Can be UUID or name (first found then)'
                                if command_description['allow_retrieve_by_name'] else 'The id (UUID)')
        if command_description['allow_creation']:
            create_parser = subparsers.add_parser('create_%s' % domain, help='Create a %s' % domain)
            create_parser.add_argument('entity', metavar='entities', type=str, nargs=1,
                                       help='Either a path of the json file containing the %s or a json object' % domain)
        if command_description['allow_deletion']:
            delete_parser = subparsers.add_parser('delete_%s' % domain, help='Delete a %s' % domain)
            delete_parser.add_argument('id', metavar='ids', type=str, nargs=1,
                                       help='The id. Can be UUID or name (first found then)'
                                       if command_description['allow_retrieve_by_name'] else 'The id (UUID)')

    arguments = parser.parse_args()
    if arguments.action == 'recent_logs':
        if is_guid(arguments.id[0]):
            log_recent(client, arguments.id[0])
        else:
            application = client.application.get_first(name=arguments.id[0])
            if application is not None:
                log_recent(client, application['metadata']['guid'])
            else:
                raise InvalidStatusCode(httplib.NOT_FOUND, 'application with name %s' % arguments.id[0])
    elif application_commands.get(arguments.action, None) is not None:
        if is_guid(arguments.id[0]):
            print(json.dumps(getattr(client.application, application_commands[arguments.action][0])(arguments.id[0]), indent=1))
        else:
            filter_get = dict(name=arguments.id[0])
            entity = client.application.get_first(**filter_get)
            if entity is None:
                raise InvalidStatusCode(httplib.NOT_FOUND, 'application with name %s' % arguments.id[0])
            else:
                print(json.dumps(getattr(client.application, application_commands[arguments.action][0])(entity['metadata']['id']), indent=1))
    elif arguments.action.find('list_') == 0:
        domain = arguments.action[len('list_'): len(arguments.action) - 1]
        filter_list = dict()
        for filter_parameter in commands[domain]['list']:
            filter_value = getattr(arguments, filter_parameter)
            if filter_value is not None:
                filter_list[filter_parameter] = filter_value
        for entity in getattr(client, domain).list(**filter_list):
            name_property = commands[domain]['name']
            if name_property is not None:
                print('%s - %s' % (entity['metadata']['guid'], entity['entity'][name_property]))
            else:
                print(entity['metadata']['guid'])
    elif arguments.action.find('get_') == 0:
        domain = arguments.action[len('get_'):]
        if is_guid(arguments.id[0]):
            print(json.dumps(getattr(client, domain).get(arguments.id[0]), indent=1))
        elif commands[domain]['allow_retrieve_by_name']:
            filter_get = dict()
            filter_get[commands[domain]['name']] = arguments.id[0]
            entity = getattr(client, domain).get_first(**filter_get)
            if entity is None:
                raise InvalidStatusCode(httplib.NOT_FOUND, '%s with name %s' % (domain, arguments.id[0]))
            else:
                print(json.dumps(entity, indent=1))
        else:
            raise ValueError('id: %s: does not allow search by name' % domain)
    elif arguments.action.find('create_') == 0:
        domain = arguments.action[len('create_'):]
        data = None
        if os.path.isfile(arguments.entity[0]):
            with open(arguments.entity[0], 'r') as f:
                try:
                    data = json.load(f)
                except ValueError, _:
                    raise ValueError('entity: file %s does not contain valid json data' % arguments.entity[0])
        else:
            try:
                data = json.loads(arguments.entity[0])
            except ValueError, _:
                raise ValueError('entity: must be either a valid json file path or a json object')
        print(json.dumps(getattr(client, domain)._create(data)))
    elif arguments.action.find('delete_') == 0:
        domain = arguments.action[len('create_'):]
        if is_guid(arguments.id[0]):
            getattr(client, domain)._remove(arguments.id[0])
        elif commands[domain]['allow_retrieve_by_name']:
            filter_get = dict()
            filter_get[commands[domain]['name']] = arguments.id[0]
            entity = getattr(client, domain).get_first(**filter_get)
            if entity is None:
                raise InvalidStatusCode(httplib.NOT_FOUND, '%s with name %s' % (domain, arguments.id[0]))
            else:
                getattr(client, domain)._remove(entity['metadata']['guid'])
        else:
            raise ValueError('id: %s: does not allow search by name' % domain)


if __name__ == "__main__":
    main()