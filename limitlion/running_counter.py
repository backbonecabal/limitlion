import math
import time
from collections import namedtuple

import pkg_resources


BucketValue = namedtuple('BucketValue', ['bucket', 'value'])


class RunningCounter:
    """
    A running counter keeps counts per interval for a specified period. The interval
    is specified in seconds and period specifies how many buckets should be kept.

    Buckets are addressed using the first epoch second for that interval calculated
    as follows:

        floor(epoch seconds / interval).

    For example, if using 1 hour intervals the bucket id for 2/19/19 01:23:09Z would be
    1550539389 / (60 * 60) = 430705. This bucket id is used to generate a Redis key with
    the following format: [key prefix]:[key]:[bucket id].

    Summing up all bucket values for the RunningCounter's window gives the total count.

    """

    def __init__(
        self, redis_instance, interval, periods, key=None, key_prefix='rc',
    ):
        """
        Inits RunningCounter class.

        Args:
            redis_instance: Redis client instance.
            interval (int): How many seconds are collected in each bucket.
            periods (int): How many buckets to key.
            key (string): Optional; Key use in Redis to track this counter.
            key_prefix (string): Optional; Prepended to key to generate Redis key.
        """
        self.redis = redis_instance
        self.key_prefix = key_prefix
        self.key = key
        self.interval = interval
        self.periods = periods

    @property
    def window(self):
        """
        Running counter window.

        Returns:
            Integer seconds for entire window of Running Counter.
        """
        return self.interval * self.periods

    def _key(self, key, bucket):
        return '{}:{}:{}'.format(self.key_prefix, key, bucket)

    def _set_key(self, key):
        if key is None:
            if self.key is None:
                raise ValueError('Key not specified')
            else:
                return self.key
        return key

    def counts(self, key=None, _now=None):
        """
        Get RunningCounter bucket counts.

        Args:
            key: Optional; Must be provided if not provided to __init__().
            _now: Optional; Override time for use by tests.

        Returns:
            List of BucketValues.
        """
        if not _now:
            _now = time.time()
        key = self._set_key(key)

        current_bucket = int(math.floor(_now / self.interval))
        buckets = [
            bucket
            for bucket in range(
                current_bucket, current_bucket - self.periods, -1
            )
        ]
        pipeline = self.redis.pipeline()
        for bucket in buckets:
            pipeline.get(self._key(key, bucket))

        counts = [None if v is None else float(v) for v in pipeline.execute()]

        bucket_values = [
            BucketValue(bv[0], bv[1])
            for bv in zip(buckets, counts)
            if bv[1] is not None
        ]
        return bucket_values

    def count(self, key=None, _now=None):
        """
        Get total count for counter.

        Args:
            key: Optional; Must be provided if not provided to __init__().
            _now: Optional; Override time for use by tests.

        Returns:
            Sum of all buckets.
        """
        key = self._set_key(key)
        return sum([bv.value for bv in self.counts(key=key, _now=_now)])

    def inc(self, increment=1, key=None, _now=None):
        """
        Update rate counter.

        Args:
            increment: Float of value to add to bucket.
            key: Optional; Must be provided if not provided to __init__().
            _now: Optional; Override time for use by tests.

        """

        # If more consistent time is needed across calling
        # processes, this method could be converted into a
        # Lua script to use Redis server time.
        if not _now:
            _now = time.time()

        key = self._set_key(key)

        bucket = int(math.floor(_now / self.interval))
        bucket_key = self._key(key, bucket)
        expire = self.periods * self.interval + 15

        pipeline = self.redis.pipeline()
        pipeline.incrbyfloat(bucket_key, increment)
        pipeline.expire(bucket_key, expire)
        pipeline.execute()