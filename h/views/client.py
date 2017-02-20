# -*- coding: utf-8 -*-

"""
Hypothesis client views.

Views which exist either to serve or support the Hypothesis client.
"""

from __future__ import unicode_literals

import json

from pyramid.config import not_
from pyramid.httpexceptions import HTTPFound
from pyramid.view import view_config
import requests

from h._compat import urlparse
from h import session as h_session
from h.auth.tokens import generate_jwt
from h.util.view import json_view
from h import __version__


def url_with_path(url):
    if urlparse.urlparse(url).path == '':
        return '{}/'.format(url)
    else:
        return url


def _resolve_client_boot_url(request):
    """
    Return the URL of the client's boot script if enabled.
    """
    if not request.feature('use_client_boot_script'):
        return None

    client_boot_url = request.registry.settings['h.client_url']
    client_script_rsp = requests.get(client_boot_url)
    client_script_rsp.raise_for_status()

    # The request for the boot script may have redirected (eg, from
    # 'https://unpkg.com/hypothesis' to
    # 'https://unpkg.com/hypothesis@X.Y.Z'), in that case use the final URL
    # to determine the asset path
    return client_script_rsp.url


def _app_html_context(assets_env, api_url, service_url, sentry_public_dsn,
                      websocket_url, auth_domain, ga_client_tracking_id,
                      client_boot_url):
    """
    Returns a dict of asset URLs and contents used by the sidebar app
    HTML tempate.
    """

    # the serviceUrl parameter must contain a path element
    service_url = url_with_path(service_url)

    app_config = {
        'apiUrl': api_url,
        'authDomain': auth_domain,
        'serviceUrl': service_url,
        'release': __version__
    }

    if websocket_url:
        app_config.update({
            'websocketUrl': websocket_url,
        })

    if sentry_public_dsn:
        app_config.update({
            'raven': {
                'dsn': sentry_public_dsn,
                'release': __version__
            }
        })

    if ga_client_tracking_id:
        app_config.update({
            'googleAnalytics': ga_client_tracking_id
        })

    app_css_urls = assets_env.urls('app_css')

    if client_boot_url:
        app_js_urls = [client_boot_url]
        app_css_urls = []
        app_config['assetRoot'] = '{}/'.format(client_boot_url)
    else:
        app_js_urls = assets_env.urls('app_js')

    return {
        'app_config': json.dumps(app_config),
        'app_css_urls': app_css_urls,
        'app_js_urls': app_js_urls,
    }


@view_config(route_name='sidebar_app',
             renderer='h:templates/app.html.jinja2')
def sidebar_app(request, extra=None):
    """
    Return the HTML for the Hypothesis client's sidebar application.

    :param extra: A dict of optional properties specifying link tags and meta
                  attributes to be included on the page.
    """

    settings = request.registry.settings
    ga_client_tracking_id = settings.get('ga_client_tracking_id')

    ctx = _app_html_context(api_url=request.route_url('api.index'),
                            client_boot_url=_resolve_client_boot_url(request),
                            service_url=request.route_url('index'),
                            sentry_public_dsn=settings.get('h.client.sentry_dsn'),
                            assets_env=request.registry['assets_client_env'],
                            websocket_url=settings.get('h.websocket_url'),
                            auth_domain=request.auth_domain,
                            ga_client_tracking_id=ga_client_tracking_id).copy()
    if extra is not None:
        ctx.update(extra)

    return ctx


# This view requires credentials (a cookie) so is not currently accessible
# off-origin, unlike the rest of the API. Given that this method of
# authenticating to the API is not intended to remain, this seems like a
# limitation we do not need to lift any time soon.
@view_config(route_name='token', renderer='string', request_method='GET')
def annotator_token(request):
    """
    Return a JWT access token for the given request.

    The token can be used in the Authorization header in subsequent requests to
    the API to authenticate the user identified by the
    request.authenticated_userid of the _current_ request, which may be None.
    """
    return generate_jwt(request, 3600)


@view_config(route_name='embed',
             renderer='h:templates/embed.js.jinja2',
             has_feature_flag=not_('use_client_boot_script'))
def embed(request):
    """
    The script which loads the Hypothesis client on a page.

    This view renders the client's boot script which loads the rest of the
    assets required by the client.

    The boot script also serves as the main script for the client's sidebar
    viewer ('app.html') application.
    """
    request.response.content_type = 'text/javascript'

    assets_env = request.registry['assets_client_env']
    base_url = request.route_url('index')

    def absolute_asset_urls(bundle_name):
        return [urlparse.urljoin(base_url, url)
                for url in assets_env.urls(bundle_name)]

    return {
        'app_html_url': request.route_url('sidebar_app'),
        'inject_resource_urls': (absolute_asset_urls('inject_js') +
                                 absolute_asset_urls('inject_css'))
    }


@view_config(route_name='embed',
             has_feature_flag='use_client_boot_script',
             http_cache=60 * 5)
def embed_redirect(request):
    """
    The script which loads the Hypothesis client on a page.

    This view redirects to the client's boot script which loads the rest of the
    assets required by the client.

    The boot script also serves as the main script for the client's sidebar
    viewer ('app.html') application.
    """
    client_boot_url = _resolve_client_boot_url(request)
    rsp = HTTPFound(location=client_boot_url)
    rsp.cache_control.max_age = 60 * 5  # 5 minutes
    return rsp


@json_view(route_name='session', http_cache=0)
def session_view(request):
    flash = h_session.pop_flash(request)
    model = h_session.model(request)
    return dict(status='okay', flash=flash, model=model)
