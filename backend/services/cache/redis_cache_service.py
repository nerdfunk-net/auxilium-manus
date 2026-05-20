"""
Cache service using Redis for persistent, distributed caching.
Supports TTL, namespaces, statistics tracking, and works across multiple processes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)


class RedisCacheService:
    """Redis-based cache service with automatic serialization and TTL support."""

    def __init__(self, redis_url: str, key_prefix: str = "manus-cache"):
        """Initialize Redis cache service.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for all cache keys to avoid collisions
        """
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix
        self._stats_key = f"{key_prefix}:stats"
        self._start_time_key = f"{key_prefix}:start_time"

        # Initialize start time if not set
        if not self._redis.exists(self._start_time_key):
            self._redis.set(self._start_time_key, str(time.time()))

        logger.info("Initialized Redis cache service with prefix '%s'", key_prefix)

    def _make_key(self, key: str) -> str:
        """Generate full Redis key with prefix."""
        return f"{self._prefix}:{key}"

    def _incr_stat(self, stat_name: str, amount: int = 1):
        """Increment a statistics counter."""
        self._redis.hincrby(self._stats_key, stat_name, amount)

    def get(self, key: str) -> Optional[Any]:
        """Get cached value by key.

        Args:
            key: Cache key (without prefix)

        Returns:
            Cached value or None if not found/expired
        """
        try:
            redis_key = self._make_key(key)
            value = self._redis.get(redis_key)

            if value is not None:
                self._incr_stat("hits")
                # Deserialize JSON
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    logger.error("Failed to deserialize cache key: %s", key)
                    self._redis.delete(redis_key)
                    return None
            else:
                self._incr_stat("misses")
                return None

        except Exception as e:
            logger.error("Cache get error for key '%s': %s", key, e)
            self._incr_stat("misses")
            return None

    def set(self, key: str, data: Any, ttl_seconds: int) -> None:
        """Set cache value with TTL.

        Args:
            key: Cache key (without prefix)
            data: Data to cache (must be JSON-serializable)
            ttl_seconds: Time to live in seconds
        """
        try:
            redis_key = self._make_key(key)
            # Serialize to JSON
            serialized = json.dumps(data)
            # Set with expiration
            self._redis.setex(redis_key, ttl_seconds, serialized)
            self._incr_stat("created")

        except (TypeError, ValueError) as e:
            logger.error("Failed to serialize cache data for key '%s': %s", key, e)
        except Exception as e:
            logger.error("Cache set error for key '%s': %s", key, e)

    def delete(self, key: str) -> bool:
        """Delete a specific cache entry by key.

        Args:
            key: The cache key to delete (without prefix)

        Returns:
            bool: True if the key existed and was deleted, False if key didn't exist
        """
        try:
            redis_key = self._make_key(key)
            deleted = self._redis.delete(redis_key)
            if deleted:
                self._incr_stat("cleared")
                return True
            return False

        except Exception as e:
            logger.error("Cache delete error for key '%s': %s", key, e)
            return False

    def clear_namespace(self, namespace: str) -> int:
        """Clear all entries in a namespace.

        Args:
            namespace: Namespace prefix (e.g., 'nautobot:devices')

        Returns:
            Number of keys deleted
        """
        try:
            # Pattern to match namespace
            pattern = self._make_key(f"{namespace}:*")
            keys = self._redis.keys(pattern)

            if keys:
                count = self._redis.delete(*keys)
                self._incr_stat("cleared", count)
                logger.info("Cleared %s keys from namespace '%s'", count, namespace)
                return count
            return 0

        except Exception as e:
            logger.error("Cache clear_namespace error for '%s': %s", namespace, e)
            return 0

    def clear_all(self) -> int:
        """Remove all cache entries (excluding stats).

        Returns:
            Number of keys deleted
        """
        try:
            # Get all cache keys except stats
            pattern = f"{self._prefix}:*"
            keys = self._redis.keys(pattern)

            # Exclude stats and start_time keys
            excluded = {self._stats_key, self._start_time_key}
            keys = [k for k in keys if k not in excluded]

            if keys:
                count = self._redis.delete(*keys)
                self._incr_stat("cleared", count)
                logger.info("Cleared all cache: %s keys deleted", count)
                return count
            return 0

        except Exception as e:
            logger.error("Cache clear_all error: %s", e)
            return 0

    def stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        try:
            now = time.time()

            # Get all cache keys (excluding stats)
            pattern = f"{self._prefix}:*"
            all_keys = self._redis.keys(pattern)
            excluded = {self._stats_key, self._start_time_key}
            cache_keys = [k for k in all_keys if k not in excluded]

            # Get stats from Redis hash
            stats_data = self._redis.hgetall(self._stats_key)
            hits = int(stats_data.get("hits", 0))
            misses = int(stats_data.get("misses", 0))
            created = int(stats_data.get("created", 0))
            cleared = int(stats_data.get("cleared", 0))

            # Get start time
            start_time_str = self._redis.get(self._start_time_key)
            start_time = float(start_time_str) if start_time_str else now

            # Calculate total size (approximate using Redis memory usage)
            total_size = 0
            for key in cache_keys:
                try:
                    # Get memory usage for this key
                    mem = self._redis.memory_usage(key)
                    if mem:
                        total_size += mem
                except Exception:
                    pass

            # Group by namespace
            namespaces = {}
            for key in cache_keys:
                # Remove prefix to get user-facing key
                user_key = (
                    key[len(self._prefix) + 1 :]
                    if key.startswith(f"{self._prefix}:")
                    else key
                )
                namespace = user_key.split(":")[0] if ":" in user_key else "default"

                if namespace not in namespaces:
                    namespaces[namespace] = {"count": 0, "size_bytes": 0}
                namespaces[namespace]["count"] += 1

                # Add memory usage to namespace
                try:
                    mem = self._redis.memory_usage(key)
                    if mem:
                        namespaces[namespace]["size_bytes"] += mem
                except Exception:
                    pass

            # Calculate hit rate
            total_requests = hits + misses
            hit_rate = (hits / total_requests * 100) if total_requests > 0 else 0

            # Get user-facing keys (without prefix)
            user_keys = [
                k[len(self._prefix) + 1 :]
                for k in cache_keys
                if k.startswith(f"{self._prefix}:")
            ]

            return {
                "overview": {
                    "total_items": len(cache_keys),
                    "valid_items": len(
                        cache_keys
                    ),  # Redis auto-expires, so all are valid
                    "expired_items": 0,  # Redis handles expiration automatically
                    "total_size_bytes": total_size,
                    "total_size_mb": round(total_size / 1024 / 1024, 2),
                    "uptime_seconds": round(now - start_time, 1),
                },
                "performance": {
                    "cache_hits": hits,
                    "cache_misses": misses,
                    "hit_rate_percent": round(hit_rate, 2),
                    "expired_entries": 0,  # Redis auto-expires
                    "entries_created": created,
                    "entries_cleared": cleared,
                },
                "namespaces": namespaces,
                "keys": user_keys,
            }

        except Exception as e:
            logger.error("Error getting cache stats: %s", e)
            return {
                "overview": {"total_items": 0, "error": str(e)},
                "performance": {},
                "namespaces": {},
                "keys": [],
            }

    def get_entries(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """Get detailed information about all cache entries.

        Args:
            include_expired: Not used (Redis auto-expires keys)

        Returns:
            List of cache entry details
        """
        try:
            time.time()
            entries = []

            # Get all cache keys
            pattern = f"{self._prefix}:*"
            all_keys = self._redis.keys(pattern)
            excluded = {self._stats_key, self._start_time_key}
            cache_keys = [k for k in all_keys if k not in excluded]

            for redis_key in cache_keys:
                # Get user-facing key
                user_key = (
                    redis_key[len(self._prefix) + 1 :]
                    if redis_key.startswith(f"{self._prefix}:")
                    else redis_key
                )
                namespace = user_key.split(":")[0] if ":" in user_key else "default"

                # Get TTL
                ttl = self._redis.ttl(redis_key)
                if ttl < 0:
                    ttl = -1  # -1 means no expiration, -2 means doesn't exist

                # Get memory usage
                try:
                    size_bytes = self._redis.memory_usage(redis_key) or 0
                except Exception:
                    size_bytes = 0

                entries.append(
                    {
                        "key": user_key,
                        "namespace": namespace,
                        "created_at": 0,  # Not tracked in Redis version
                        "expires_at": 0,  # Not available
                        "last_accessed": 0,  # Not tracked
                        "access_count": 0,  # Not tracked per-key
                        "size_bytes": size_bytes,
                        "age_seconds": 0,  # Not tracked
                        "ttl_seconds": max(ttl, 0),
                        "last_accessed_ago": 0,  # Not tracked
                        "is_expired": False,  # Redis auto-expires
                    }
                )

            # Sort by key name
            entries.sort(key=lambda x: x["key"])
            return entries

        except Exception as e:
            logger.error("Error getting cache entries: %s", e)
            return []

    def get_namespace_info(self, namespace: str) -> Dict[str, Any]:
        """Get detailed information about a specific namespace.

        Args:
            namespace: Namespace to query (e.g., 'nautobot:devices')

        Returns:
            Dictionary with namespace statistics and entries
        """
        try:
            entries = []
            total_size = 0

            # Get keys matching this namespace
            pattern = self._make_key(f"{namespace}:*")
            keys = self._redis.keys(pattern)

            for redis_key in keys:
                # Get user-facing key
                user_key = (
                    redis_key[len(self._prefix) + 1 :]
                    if redis_key.startswith(f"{self._prefix}:")
                    else redis_key
                )

                # Get TTL
                ttl = self._redis.ttl(redis_key)
                if ttl < 0:
                    ttl = -1

                # Get memory usage
                try:
                    size_bytes = self._redis.memory_usage(redis_key) or 0
                    total_size += size_bytes
                except Exception:
                    size_bytes = 0

                entries.append(
                    {
                        "key": user_key,
                        "created_at": 0,
                        "expires_at": 0,
                        "last_accessed": 0,
                        "access_count": 0,
                        "size_bytes": size_bytes,
                        "ttl_seconds": max(ttl, 0),
                        "is_expired": False,
                    }
                )

            return {
                "namespace": namespace,
                "total_entries": len(entries),
                "valid_entries": len(entries),
                "expired_entries": 0,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "entries": entries,
            }

        except Exception as e:
            logger.error("Error getting namespace info for '%s': %s", namespace, e)
            return {
                "namespace": namespace,
                "total_entries": 0,
                "valid_entries": 0,
                "expired_entries": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "entries": [],
            }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get detailed performance metrics."""
        try:
            now = time.time()

            # Get stats from Redis
            stats_data = self._redis.hgetall(self._stats_key)
            hits = int(stats_data.get("hits", 0))
            misses = int(stats_data.get("misses", 0))
            created = int(stats_data.get("created", 0))
            cleared = int(stats_data.get("cleared", 0))

            # Get start time
            start_time_str = self._redis.get(self._start_time_key)
            start_time = float(start_time_str) if start_time_str else now
            uptime = now - start_time

            # Get current entry count
            pattern = f"{self._prefix}:*"
            all_keys = self._redis.keys(pattern)
            excluded = {self._stats_key, self._start_time_key}
            cache_keys = [k for k in all_keys if k not in excluded]

            total_requests = hits + misses

            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": total_requests,
                "requests_per_second": round(total_requests / uptime, 2)
                if uptime > 0
                else 0,
                "cache_hits": hits,
                "cache_misses": misses,
                "hit_rate_percent": round(
                    (hits / total_requests * 100) if total_requests > 0 else 0, 2
                ),
                "expired_entries": 0,  # Redis handles automatically
                "entries_created": created,
                "entries_cleared": cleared,
                "current_entries": len(cache_keys),
            }

        except Exception as e:
            logger.error("Error getting performance metrics: %s", e)
            return {
                "uptime_seconds": 0,
                "total_requests": 0,
                "requests_per_second": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "hit_rate_percent": 0,
                "expired_entries": 0,
                "entries_created": 0,
                "entries_cleared": 0,
                "current_entries": 0,
            }

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count of removed items.

        Note: Redis handles expiration automatically, so this is a no-op.
        Returns 0 as no manual cleanup is needed.
        """
        logger.info("cleanup_expired called - Redis handles expiration automatically")
        return 0
