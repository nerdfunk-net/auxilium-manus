# Description of all data types used in the workflow steps  

## Basis data class

All other datatypes are inherited by this data class.


## device_list

  "general": {
      "source_id": "prod",
      "total": 7
  },
  "device_ids": [
    "16f5899b-b0b4-4738-b187-840c41040e02"
  ],
  "device_details": [
    {
      "id": "16f5899b-b0b4-4738-b187-840c41040e02",
      "name": "lab-001",
      "primary_ip4": {
        "address": "192.168.178.36/24"
      },
      "platform": {
        "name": "Cisco IOS",
        "manufacturer": null,
        "network_driver": "cisco_ios"
      }
    }
  ]

## device_attribute_map

  "general": {
      "source_id": "prod",
      "total": 1
  },
  "device_ids": [
    "16f5899b-b0b4-4738-b187-840c41040e02",
  ],
  "device_details": [
    {
      "id": "16f5899b-b0b4-4738-b187-840c41040e02",
      "name": "lab-001",
      "hostname": "lab-001",
      "asset_tag": null,
      "serial": "NET0000001",
      "position": null,
      "face": null,
      "config_context": {},
      "local_config_context_data": null,
      "_custom_field_data": {
        "net": "netA",
        "last_backup": "2025-02-20",
        "checkmk_site": "siteC",
        "free_textfield": "Network device in Another City C",
        "snmp_credentials": "credB"
      },
      "primary_ip4": {
        "id": "5ec3f3b6-b7f5-4ba4-aaba-f9de7b483504",
        "address": "192.168.178.36/24",
        "description": "",
        "ip_version": 4,
        "host": "192.168.178.36",
        "mask_length": 24,
        "dns_name": "",
        "status": {
          "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
          "name": "Active"
        },
        "parent": {
          "id": "742bfc4e-94c8-43d9-a7e8-6df1dfbade09",
          "prefix": "192.168.178.0/24"
        }
      },
      "role": {
        "id": "d483af02-d92f-481d-b927-c128e50a5ac3",
        "name": "Network"
      },
      "device_type": {
        "id": "50ddc6c6-93b8-42f0-a86c-1da79bbe8957",
        "model": "networkA",
        "manufacturer": {
          "id": "ba63b249-2c4d-46cd-ab46-8f1ba2bfcde1",
          "name": "NetworkInc"
        }
      },
      "platform": {
        "id": "daa2387e-696a-46fd-8040-a388bb295cd3",
        "name": "Cisco IOS",
        "network_driver": "cisco_ios",
        "manufacturer": null
      },
      "location": {
        "id": "d8944720-50c0-4eb4-889c-4fe236720ddb",
        "name": "Another City C",
        "description": "Another City C",
        "parent": {
          "id": "c8683896-7b4f-4bc7-8952-68c071928937",
          "name": "State C"
        }
      },
      "status": {
        "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
        "name": "Active"
      },
      "interfaces": [
        {
          "id": "552b7b5a-e3aa-41ae-b01a-18d2b74bfa8b",
          "name": "GigabitEthernet1/0/1",
          "type": "A_1000BASE_T",
          "enabled": true,
          "mtu": null,
          "mac_address": null,
          "description": "",
          "status": {
            "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
            "name": "Active"
          },
          "ip_addresses": [
            {
              "id": "5ec3f3b6-b7f5-4ba4-aaba-f9de7b483504",
              "address": "192.168.178.36/24",
              "ip_version": 4,
              "status": {
                "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
                "name": "Active"
              }
            }
          ],
          "connected_interface": null,
          "cable": null,
          "tagged_vlans": [],
          "untagged_vlan": null
        },
        {
          "id": "d514ec33-bcfa-491a-8c8b-8787832ee15b",
          "name": "GigabitEthernet1/0/2",
          "type": "A_1000BASE_T",
          "enabled": true,
          "mtu": null,
          "mac_address": null,
          "description": "",
          "status": {
            "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
            "name": "Active"
          },
          "ip_addresses": [
            {
              "id": "345c6f8f-c4de-43e5-995d-9132748f0342",
              "address": "192.168.179.36/24",
              "ip_version": 4,
              "status": {
                "id": "1097e3a2-bb37-4b11-ab10-d522d1084c9d",
                "name": "Active"
              }
            }
          ],
          "connected_interface": null,
          "cable": null,
          "tagged_vlans": [],
          "untagged_vlan": null
        }
      ],
      "tags": [
        {
          "id": "d84f2fa9-58a3-4d9a-8c5b-4eb21c759085",
          "name": "Production",
          "color": "4caf50"
        }
      ]
    },
  ]
