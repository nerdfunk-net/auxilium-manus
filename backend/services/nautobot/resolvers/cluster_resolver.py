"""
Cluster resolver for Nautobot virtualization cluster operations.

This resolver handles read-only operations for virtualization clusters.
"""

import logging
from typing import Any, Dict, List, Optional

from ..common.exceptions import NautobotAPIError
from .base_resolver import BaseResolver

logger = logging.getLogger(__name__)


class ClusterResolver(BaseResolver):
    """Resolver for virtualization cluster operations."""

    async def get_all_cluster_groups(self) -> List[Dict[str, Any]]:
        """
        Get all cluster groups from Nautobot.

        Returns:
            List of cluster group dictionaries with id and name

        Raises:
            Exception: If GraphQL query fails
        """
        query = """
        {
          cluster_groups {
            id
            name
          }
        }
        """
        try:
            result = await self.nautobot.graphql_query(query)

            if "errors" in result:
                logger.error(
                    "GraphQL errors fetching cluster groups: %s", result["errors"]
                )
                raise NautobotAPIError(f"GraphQL errors: {result['errors']}")

            cluster_groups = result.get("data", {}).get("cluster_groups", [])
            logger.info(
                "Retrieved %s cluster groups from Nautobot", len(cluster_groups)
            )
            return cluster_groups

        except Exception as e:
            logger.error("Failed to fetch cluster groups: %s", e, exc_info=True)
            raise

    async def get_all_clusters(
        self, group: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all clusters from Nautobot, optionally filtered by cluster group.

        Args:
            group: Optional list of cluster group IDs to filter by

        Returns:
            List of cluster dictionaries with virtual machines and device assignments

        Raises:
            Exception: If GraphQL query fails
        """
        query = """
        query ($group: [String]) {
          clusters(cluster_group: $group) {
            id
            name
            cluster_group {
              id
              name
            }
            virtual_machines {
              id
              name
            }
            device_assignments {
              id
              device {
                id
                name
              }
            }
          }
        }
        """
        try:
            variables = {"group": group} if group else {}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL errors fetching clusters: %s", result["errors"])
                raise NautobotAPIError(f"GraphQL errors: {result['errors']}")

            clusters = result.get("data", {}).get("clusters", [])
            if group:
                logger.info(
                    "Retrieved %s clusters from Nautobot (filtered by group: %s)",
                    len(clusters),
                    group,
                )
            else:
                logger.info("Retrieved %s clusters from Nautobot", len(clusters))
            return clusters

        except Exception as e:
            logger.error("Failed to fetch clusters: %s", e, exc_info=True)
            raise

    async def get_cluster_by_id(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific cluster by ID from Nautobot.

        Args:
            cluster_id: UUID of the cluster

        Returns:
            Cluster dictionary with virtual machines and device assignments, or None if not found

        Raises:
            Exception: If GraphQL query fails
        """
        query = """
        query getCluster($id: ID!) {
          clusters(id: $id) {
            id
            name
            virtual_machines {
              id
              name
            }
            device_assignments {
              id
              device {
                id
                name
              }
            }
          }
        }
        """
        try:
            result = await self.nautobot.graphql_query(query, {"id": cluster_id})

            if "errors" in result:
                logger.error(
                    "GraphQL errors fetching cluster %s: %s",
                    cluster_id,
                    result["errors"],
                )
                raise NautobotAPIError(f"GraphQL errors: {result['errors']}")

            clusters = result.get("data", {}).get("clusters", [])
            if clusters:
                logger.info("Retrieved cluster %s from Nautobot", cluster_id)
                return clusters[0]
            else:
                logger.warning("Cluster %s not found in Nautobot", cluster_id)
                return None

        except Exception as e:
            logger.error("Failed to fetch cluster %s: %s", cluster_id, e, exc_info=True)
            raise
