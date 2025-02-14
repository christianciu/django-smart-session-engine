from typing import List
from .utils import get_redis_connection, get_user_key

from django.conf import settings
from django.contrib.sessions.backends.cache import SessionStore as CacheSessionStore


class SessionStore(CacheSessionStore):

    def _get_key(self, user_id):
        # What we want
        # return "%s:session_id:%s" % (self._cache.key_prefix, user_id)

        # This is the original
        return "session_id:%s" % user_id

    def save(self, *args, **kwargs):
        must_create = kwargs.get('must_create', False)
        super(SessionStore, self).save(must_create)

        redis = get_redis_connection()
        user_id = self._get_session(no_load=must_create).get('_auth_user_id', None)
        if user_id:
            key = self._get_key(user_id)
            pipeline = redis.pipeline()
            pipeline.sadd(key, self.session_key)
            pipeline.expire(key, settings.SESSION_COOKIE_AGE)
            pipeline.execute()

    def delete(self, session_key=None):
        """ This only triggered on explicit logout """
        redis = get_redis_connection()
        session_key = session_key or self.session_key
        user_id = self.load().get('_auth_user_id', None)
        if user_id:
            redis.srem(self._get_key(user_id), session_key)

        super(SessionStore, self).delete(session_key)

    def delete_multiples_session_keys(self, list_of_users: List):
        redis = get_redis_connection()
        # First pipeline to get all keys
        get_pipeline = redis.pipeline()

        # Queue up all smembers commands
        for user in list_of_users:
            get_pipeline.smembers(get_user_key(user))

        # Execute and get all session keys
        all_sessions = get_pipeline.execute()

        # Second pipeline for deletion
        delete_pipeline = redis.pipeline()

        # Process results and queue deletions
        for user, sessions in zip(list_of_users, all_sessions):
            decoded_keys = [key.decode('utf-8') for key in sessions]
            for session_key in decoded_keys:
                delete_pipeline.srem(self._get_key(str(user.id)), session_key)
                # Call parent's delete function to delete cache
                super(SessionStore, self).delete(session_key)

        delete_pipeline.execute(raise_on_error=True)
