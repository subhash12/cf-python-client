import logging

from cloudfoundry.calls import caller
from cloudfoundry.credentials import CredentialsManager
from organizations import OrganizationManager
from spaces import SpaceManager
from services import ServiceManager
from applications import ApplicationsManager

_logger = logging.getLogger(__name__)


class InvalidStatusCode(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


class CloudFoundryClient(object):
    proxy = None

    def __init__(self, target_endpoint, client_id='cf', client_secret='', proxy=None, skip_verification=False):
        caller.proxy(proxy)
        caller.skip_verifications(skip_verification)
        self.target_endpoint = target_endpoint
        self.info = caller.get('%s/v2/info' % self.target_endpoint).json()
        self.credentials_manager = CredentialsManager(self.info, client_id, client_secret)
        self.organization = OrganizationManager(self.target_endpoint, self.credentials_manager)
        self.space = SpaceManager(self.target_endpoint, self.credentials_manager)
        self.service = ServiceManager(self.target_endpoint, self.credentials_manager)
        self.application = ApplicationsManager(self.target_endpoint, self.credentials_manager)

    def init_with_credentials(self, login, password):
        self.credentials_manager.init_with_credentials(login, password)

    def init_with_refresh(self, refresh_token):
        self.credentials_manager.init_with_refresh(refresh_token)


