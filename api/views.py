__author__ = 'mstacy'
from rest_framework import permissions
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework import serializers
# generics
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
# from .models import AuthtokenToken, AuthUser
# from django.contrib.auth.decorators import login_required
from hashlib import md5
from django.contrib.auth.models import Group
# logout request
import requests
import os
import json
from django.contrib.auth import logout
from django.conf import settings

from rest_framework.parsers import FileUploadParser, MultiPartParser
from rest_framework.renderers import JSONRenderer
from api import config
from pymongo import MongoClient
from data_store.mongo_paginator import MongoDataPagination

default_user_group = os.getenv('DEFAULT_USER_GROUP', 'cubl-default-login')
security_grouper_collection = os.getenv('SECURITY_GROUPER_COLLECTION',
                                        'application_grouper')

class APIRoot(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request, format=None):
        data={
            'Queue': {
                'Tasks': reverse('queue-main', request=request),
                'Tasks History': reverse('queue-user-tasks', request=request)
            },
            'Catalog': {
                'Data Source': reverse('catalog-list', request=request),
                'Ark Server': reverse('ark-list', request=request)
            },
            'Data Store': {
                'Mongo': reverse('data-list', request=request),
                'Counter': [ reverse('platform-list', request=request),
                            reverse('filter-list', request=request),
                            reverse('title-list', request=request)],
                'S3': [ reverse('buckets-list', request=request),
                        reverse('objects-list', request=request)]
            },
            'User Profile': {'User': reverse('user-list', request=request)}        }
        return Response(data)


class UserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)


class samlLogout(APIView):

    def get(self, request, id=None, format=None):
        """
        Logout of django and SAML post for CU Boulder Idp logout
        """
        requests.post(
            "https://fedauth-test.colorado.edu/idp/profile/Logout/", data="_eventId=propagate")
        requests.post(
            "https://fedauth-test.colorado.edu/idp/profile/SAML2/Redirect/SLO")
        logout(request)


class appGroupPermissions(permissions.BasePermission):
    """
        This permission is included for application that require a specific Group.
        Process:
        1. NO app parameter set in url(?app=libbudget) ==> action allowed
        2. No group set within MongoDB for app parameter(?app=libbudget) ==> action allowed
        3. Group set in MongoDB collection that match user group ==> action allowed
        4. Group set in MongoDB collection that does not match users grouper groups ==> action denied

        Security MongoDB collection: default 'application_grouper' 
          Environmental Variable: SECURITY_GROUPER_COLLECTION
    """

    def has_permission(self, request, view):
        application = request.query_params.get('app')
        connect_uri = config.DATA_STORE_MONGO_URI
        db = MongoClient(host=connect_uri)
        query={"filter":{"application":application}}
        app_required_group = MongoDataPagination(db,'catalog',security_grouper_collection,query=json.dumps(query),nPerPage=0)
        if application is not None:
            user_groups,user_departments=UserGroups().groups(request)
            for app in app_required_group['results']:
                if app['group'] not in user_groups:
                    return False
            return True
        else:
            return True

class grouperPermissions(permissions.BasePermission):
    """
        This permission is included for application that require a specific 
        Grouper group.  It does not look at the cybercom user object and 
        groups assigned to user in cybercom.
        The permission is allowed only if the application has set the
        required groups in mongo and the user is a member of all the required
        Grouper groups.
    """
    def has_permission(self, request, view):
        # determine which application is requesting this permission check
        application = request.query_params.get('app')

        connect_uri = config.DATA_STORE_MONGO_URI
        db = MongoClient(host=connect_uri)
        query={"filter":{"application":application}}
        app_required_group = MongoDataPagination(db,'catalog',security_grouper_collection,query=json.dumps(query),nPerPage=0)

        user_groups, user_departments = GrouperGroups().groups(request)

        if application is not None and (app_required_group['count'] > 0) and user_groups is not None:
            # Check user has each required group
            for app in app_required_group['results']:
                if app['group'] not in user_groups:
                    return False
            return True
        else:
            return False

class UserGroups():
    def groups(self,request):
        user_groups = []
        user_departments = []

        for g in request.user.groups.all():
            user_groups.append(g.name)
        if default_user_group not in user_groups:
            my_group = Group.objects.get(name=default_user_group)
            my_group.user_set.add(request.user)
            user_groups.append(default_user_group)

        # Append the user's Grouper groups
        grouper_groups, user_departments = GrouperGroups().groups(request)
        user_groups = list(set(user_groups+grouper_groups))

        user_groups.sort()
        return user_groups, user_departments

class GrouperGroups():
    def groups(self, request):
        groups = []
        departments = [] 

        if 'samlUserdata' in request.session:
            samlUserdata = request.session['samlUserdata']
            if "urn:oid:1.3.6.1.4.1.632.11.2.200" in samlUserdata:
                groups = list(samlUserdata['urn:oid:1.3.6.1.4.1.632.11.2.200'])
            if "urn:oid:1.3.6.1.4.1.632.11.1.15" in samlUserdata:
                departments = list(samlUserdata["urn:oid:1.3.6.1.4.1.632.11.1.15"])

        return groups, departments

class UserProfile(APIView):
    permission_classes = (IsAuthenticated, appGroupPermissions,)
    serializer_class = UserSerializer
    fields = ('username', 'first_name', 'last_name', 'email')
    model = User

    def get(self, request, id=None, format=None):
        data = User.objects.get(pk=self.request.user.id)
        serializer = self.serializer_class(data, context={'request': request})
        tok = Token.objects.get_or_create(user=self.request.user)
        user_groups,user_departments=UserGroups().groups(request)
        rdata = serializer.data
        rdata['name'] = data.get_full_name()
        rdata['department']=user_departments
        rdata['gravator_url'] = "{0}://www.gravatar.com/avatar/{1}".format(
            request.scheme, md5(rdata['email'].lower().strip(' \t\n\r').encode('utf-8')).hexdigest())
        rdata['groups'] = user_groups
        authscheme = {'auth-token': str(tok[0])}
        rdata['authentication'] = authscheme
        return Response(rdata)

    def post(self, request, format=None):
        user = User.objects.get(pk=self.request.user.id)
        password = request.data.get('password', None)
        if password:
            user.set_password(password)
            user.save()
            data = {"password": "Successfully Updated"}
            return Response(data)
        auth_tok = request.data.get('auth-token', None)
        if str(auth_tok).lower() == "update":
            tok = Token.objects.get(user=user)
            tok.delete()
            tok = Token.objects.get_or_create(user=self.request.user)
            data = {"auth-token": str(tok[0])}
            return Response(data)
        else:
            user.first_name = request.data.get('first_name', user.first_name)
            user.last_name = request.data.get('last_name', user.last_name)
            user.email = request.data.get('email', user.email)
            serializer = self.serializer_class(
                user, context={'request': request})
            data = serializer.data
            user.save()
            tok = Token.objects.get_or_create(user=self.request.user)
            data['name'] = user.get_full_name()
            data['gravator_url'] = "{0}://www.gravatar.com/avatar/{1}".format(
                request.scheme, md5(data['email'].strip(' \t\n\r').encode('utf-8')).hexdigest())
            data['auth-token'] = str(tok[0])
            return Response(data)

class GrouperGroupProfile(APIView):
    permission_classes = (IsAuthenticatedOrReadOnly, grouperPermissions)

    def get(self, request, id=None, format=None):
        rdata = {
            'username': '',
            'email': '',
            'first_name': '',
            'last_name': '',
            'user_affiliations': ''
        }

        if 'samlUserdata' in request.session:
            samlUserData = request.session['samlUserdata']

            saml_mappings = settings.SAML_USERS_MAP[0]['MyProvider']
            rdata['username'] = samlUserData[
                saml_mappings['username']['key']][
                saml_mappings['username']['index']]
            rdata['email'] = samlUserData[
                saml_mappings['email']['key']][
                saml_mappings['email']['index']]
            rdata['first_name'] = samlUserData[
                saml_mappings['first_name']['key']][
                saml_mappings['first_name']['index']]
            rdata['last_name'] = samlUserData[
                saml_mappings['last_name']['key']][
                saml_mappings['last_name']['index']]
            if "urn:oid:1.3.6.1.4.1.5923.1.1.1.1" in samlUserData:
                rdata['user_affiliations'] = samlUserData["urn:oid:1.3.6.1.4.1.5923.1.1.1.1"]
        return Response(rdata)


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the snippet.
        return obj.owner == request.user


class fileDataUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    # parser_classes = (MultiPartParser, FormParser, FileUploadParser,)
    parser_classes = (MultiPartParser, FileUploadParser,)
    renderer_classes = (JSONRenderer,)

    def post(self, request, uploadDirectory="/data/file_upload", format=None):
        # check if uploadDirectory exists
        if not os.path.isdir(uploadDirectory):
            os.makedirs(uploadDirectory)
        results = []
        # upload files submitted

        # print( request.data )
        file_obj = request.data['file']
        #print(dir(file_obj))
        filename = file_obj.name
        local_file = "{0}/{1}".format(uploadDirectory, filename)
        self.handle_file_upload(request.data['file'], local_file)
        result = {}
        if request.data.get("callback", None):
            req = self.callback_task(request, local_file)
            try:
                result['callback'] = {
                    "status": req.status_code, "response": req.json()}
            except:
                result['callback'] = {
                    "status": req.status_code, "response": req.text}
        results.append(result)

        return Response(results)

    def handle_file_upload(self, f, filename):
        if f.multiple_chunks():
            with open(filename, 'wb+') as temp_file:
                for chunk in f.chunks():
                    temp_file.write(chunk)
        else:
            with open(filename, 'wb+') as temp_file:
                temp_file.write(f.read())

    def callback_task(self, request, local_file):
        # Get Token for task submission
        tok = Token.objects.get_or_create(user=request.user)
        headers = {'Authorization': 'Token {0}'.format(
            str(tok[0])), 'Content-Type': 'application/json'}
        queue = request.data.get("queue", "celery")
        # tags is a comma separated string; Converted to list
        tags = request.data.get("tags", '')
        tags = tags.split(',')
        taskname = request.data.get("callback")
        data = request.data
        del data['file']
        payload = {"function": taskname, "queue": queue, "args": [
            local_file, data], "kwargs": {}, "tags": tags}
        components = request.build_absolute_uri('/api/')  # .split('/')
        #hostname = os.environ.get("api_hostname", components[2])
        url = "{0}queue/run/{1}.json".format(components, taskname)
        return requests.post(url, data=json.dumps(payload), headers=headers)
