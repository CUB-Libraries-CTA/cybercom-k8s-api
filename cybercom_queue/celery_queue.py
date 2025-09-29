import math
import re
import pickle  #nosec
import collections
import json
from pymongo import MongoClient, DESCENDING
from rest_framework.reverse import reverse
from collections import OrderedDict
from datetime import datetime
from celery import Celery
from api import config

app = Celery()

class celeryConfig:
    BROKER_URL = config.BROKER_URL
    BROKER_USE_SSL = config.BROKER_USE_SSL
    CELERY_SEND_EVENTS = True
    CELERY_TASK_RESULT_EXPIRES = None
    CELERY_RESULT_BACKEND = config.CELERY_RESULT_BACKEND
    CELERY_MONGODB_BACKEND_SETTINGS = config.CELERY_MONGODB_BACKEND_SETTINGS


def check_memcache(host=config.MEMCACHE_HOST, port=config.MEMCACHE_PORT):
    """ Check if memcache is running on server """
    import socket

    s = socket.socket()
    try:
        s.connect((host, port))
        return True
    except:
        return False


class QueueTask():
    def __init__(self, database=config.MONGO_DB,
                 log_collection=config.MONGO_LOG_COLLECTION, 
                 tomb_collection=config.MONGO_TOMBSTONE_COLLECTION, 
                 memcache=check_memcache()):
        self.db = MongoClient(config.DATA_STORE_MONGO_URI)
        self.database = database
        self.collection = log_collection
        self.tomb_collection = tomb_collection
        self.memcache=memcache
        app.config_from_object(celeryConfig)
        self.i = app.control.inspect()
        
    def run(self, task, task_args, task_kwargs, task_queue, user_info, tags):
        """ 
        Submit task to celerey async tasks
        """
        print(user_info)
        # Submit task
        task_obj = app.send_task(
            task, args=task_args, kwargs=task_kwargs, queue=task_queue, track_started=True,headers={"authenticated_user":user_info})
        task_log = {
            'task_id': task_obj.task_id,
            'user': user_info['username'],
            'task_name': task,
            'args': task_args,
            'kwargs': task_kwargs,
            'queue': task_queue,
            'timestamp': datetime.now(),
            'tags': tags
        }
        self.db[self.database][self.collection].insert(task_log)

        return {"task_id": task_obj.task_id}

    def list_tasks(self):
        """ List available tasks """
        REGISTERED_TASKS, AVAILABLE_QUEUES = self.update_tasks()
        # print REGISTERED_TASKS, AVAILABLE_QUEUES
        REGISTERED_TASKS = [task for task in list(
            REGISTERED_TASKS) if task[0:6] != "celery"]
        AVAILABLE_QUEUES = list(AVAILABLE_QUEUES)
        REGISTERED_TASKS.sort()
        AVAILABLE_QUEUES.sort()
        return {"available_tasks": REGISTERED_TASKS, "available_queues": AVAILABLE_QUEUES}
        #return list_tasks()

    def status(self, task_id=None):
        """ Return a task's status """
        col = self.db[self.database][self.tomb_collection]
        if task_id:
            result = [item for item in col.find({'_id': task_id})]
            if len(result) == 0:
                try:
                    res = app.AsyncResult(task_id)
                    return {"status": "%s" % (res.status), "task_id": "%s" % (task_id)}
                except:
                    raise
                    # return {"status": "ERROR IN OBTAINING STATUS", "task_id": "%s" % (task_id)}
            else:
                return {"status": result[0]['status']}
        else:
            raise Exception("Not a valid task_id")

    def result(self, task_id=None, redirect=True):
        """ Get the result of a task  """
        col = self.db[self.database][self.tomb_collection]
        if task_id:
            result = [item for item in col.find({'_id': task_id})]
            try:
                result = pickle.loads(result[0]['result'])
                return result
            except:
                raise Exception("Not a valid task_id")
        else:
            raise Exception("Not a valid task_id")

    def task(self, task_id=None):
        """Return task log and task results"""
        doc = self.db[self.database][self.collection].find_one(
            {'task_id': task_id}, {'_id': False})
        col = self.db[self.database][self.tomb_collection]
        if doc:
            result = col.find_one({'_id': task_id}, {'_id': False})
            if result:
                result = self.unpickle_result(result)
            else:
                result = self.status(task_id=task_id)
            doc['result'] = result
            return doc
        else:
            result = col.find_one({'_id': task_id}, {'_id': False})
            if result:
                result = self.unpickle_result(result)
                return result
            else:
                result = self.status(task_id=task_id)
            return result

    def unpickle_result(self, result):
        if 'traceback' in result:
            if type(result['traceback']) == bytes:
                result['traceback'] = pickle.loads(result['traceback'])
            try:
                result['traceback'] =json.loads(result['traceback'])
            except:
                pass
        if 'children' in result:
            if type(result['children']) == bytes:
                result['children'] = pickle.loads(result['children'])
            try:
                result['children'] =json.loads(result['children'])
            except:
                pass

        if 'result' in result:
            if type(result['result']) == bytes:
                result['result'] = pickle.loads(result['result'])
            if isinstance(result['result'], Exception):
                result['result'] = "ERROR: {0}".format(str(result['result']))
            try:
                result['result'] =json.loads(result['result'])
            except:
                pass
        return result

    def reset_tasklist(self, user="guest"):
        """ 
        Delete and reload memcached record of available tasks, useful for development
        when tasks are being frequently reloaded.
        """
        if self.memcache:
            import memcache
            mc = memcache.Client(
                ['%s:%s' % (config.MEMCACHE_HOST, config.MEMCACHE_PORT)])
            tasks = "REGISTERED_TASKS_%s" % user
            queues = "AVAILABLE_QUEUES_%s" % user
            mc.delete(tasks)
            mc.delete(queues)
        return self.list_tasks()
        

    def history(self, user, task_name=None, page=1, limit=0, request=None):
        """ Show a history of tasks """
        if page < 1:
            page = 1
        limit = int(limit)
        col = self.db[self.database][self.collection]
        result = {'count': 0, 'next': None, 'previous': None, 'results': []}
        history = []
        if task_name:
            tasks_list=task_name.split(',')
            result['count'] = col.find(
                {'task_name': {"$in":tasks_list}, 'user': user}).count()
            data = col.find({'task_name': {"$in":tasks_list}, 'user': user}, {'_id': False}, skip=(page - 1) * limit,
                            limit=limit).sort('timestamp', DESCENDING)
        else:
            data = col.find({'user': user}, {'_id': False}, skip=(page - 1) * limit, limit=limit).sort('timestamp',
                                                                                                       DESCENDING)
            result['count'] = col.find({'user': user}).count()
        if result['count'] <= page*limit:
            if page != 1:
                result['previous'] = "%s?page=%d&page_size=%d" % (
                    reverse('queue-user-tasks', request=request), page-1, limit)
        if result['count'] >= page*limit:
            if result['count'] != page*limit:
                result['next'] = "%s?page=%d&page_size=%d" % (
                    reverse('queue-user-tasks', request=request), page+1, limit)
            if page > 1:
                result['previous'] = "%s?page=%d&page_size=%d" % (
                    reverse('queue-user-tasks', request=request), page-1, limit)
        result['meta'] = {'page': page, 'page_size': limit,
                          'pages': math.ceil(float(result['count'])/float(limit))}
        for item in data:
            if type(item['kwargs']) is dict:
                for i, v in item['kwargs'].items():
                    try:
                        item['kwargs'][i] = json.loads(v)
                    except:
                        pass
            try:
                item['result'] = reverse(
                    'queue-task-result', kwargs={'task_id': item['task_id']}, request=request)
            except:
                item['result'] = ""
            history.append(item)
        result['results'] = history
        try:
            od = collections.OrderedDict(sorted(result.items()))
        except:
            # older python versions < 2.7
            od = OrderedDict(sorted(result.items()))
        return od

    def task_docstring(self, taskname):
        """
        Get task docstring of a registered tasks from celery.
        """
        data = self.i.registered('__doc__')

        for x, v in data.items():
            for task in v:
                name, doc = self.get_taskname_doc(task, ']')
                if name.strip() == taskname.strip():
                    doc=doc.replace('.\n',' ')
                    doc=doc.replace('\n','. ')
                    return doc
        return None

    def get_taskname_doc(self, thestring, ending):
        temp = thestring.split('[__doc__=')
        if len(temp) > 1:
            if temp[1].endswith(ending):
                return temp[0], re.sub(' +', ' ', temp[1][:-len(ending)])
            return temp[0], re.sub(' +', ' ', temp[1])
        return temp[0], ""

    def update_tasks(self,timeout=60000, user="guest"):
        """ 
        Get list of registered tasks from celery, store in memcache for 
            `timeout` period if set (default to 6000s) if available 
        """
        try:
            if self.memcache:
                import memcache
                mc = memcache.Client(
                    ['%s:%s' % (config.MEMCACHE_HOST, config.MEMCACHE_PORT)])
                tasks = "REGISTERED_TASKS_%s" % user
                queues = "AVAILABLE_QUEUES_%s" % user
                REGISTERED_TASKS = mc.get(tasks)
                AVAILABLE_QUEUES = mc.get(queues)
                if not REGISTERED_TASKS:
                    REGISTERED_TASKS = set()
                    for item in self.i.registered().values():
                        REGISTERED_TASKS.update(item)
                    mc.set(tasks, REGISTERED_TASKS, timeout)
                    REGISTERED_TASKS = mc.get(tasks)
                if not AVAILABLE_QUEUES:
                    mc.set(queues, set([item[0]["exchange"]["name"]
                                        for item in self.i.active_queues().values()]), timeout)
                    AVAILABLE_QUEUES = mc.get(queues)
            else:
                REGISTERED_TASKS = set()
                for item in self.i.registered().values():
                    REGISTERED_TASKS.update(item)
                AVAILABLE_QUEUES = set([item[0]["exchange"]["name"]
                                        for item in self.i.active_queues().values()])
        except:
            REGISTERED_TASKS = set()
            AVAILABLE_QUEUES = set()
        return (REGISTERED_TASKS, AVAILABLE_QUEUES)
