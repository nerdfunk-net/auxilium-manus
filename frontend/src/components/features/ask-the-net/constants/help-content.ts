/** One tool the assistant can use, with questions that make it use that tool. */
export interface HelpTool {
  /** The tool's name as the assistant sees it. */
  readonly name: string;
  readonly description: string;
  readonly questions: readonly string[];
}

export interface HelpSection {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  /** Shown under the summary when the section needs something the user may not have. */
  readonly requirement?: string;
  readonly tools: readonly HelpTool[];
}

/**
 * The help page of Ask the Net: every tool group, what each tool does and questions that use it.
 * Keep it in step with the tool list in doc/AI_TOOL_CHAIN.md and `build_general_session`.
 */
export const HELP_SECTIONS: readonly HelpSection[] = [
  {
    id: "playbooks",
    title: "Playbooks",
    summary:
      "Ready-made procedures that gather facts from the network in a fixed, reviewed order and sum them up in one table. They are not only for troubleshooting: use them to check a device, get an overview, find a host or read a configuration. Ask the question in your own words and the assistant picks the matching playbook; it names the playbook it used. Your organisation can add its own playbooks.",
    requirement:
      "Each playbook uses the tools of the sections below, so what you may ask follows your permissions. The list shows which tools you lack for a playbook. Playbooks that run commands on a device need a confirmation on the card, as described under Device commands.",
    tools: [
      {
        name: "list_playbooks / get_playbook",
        description:
          "Lists every playbook with the questions it answers and the tools it needs, and loads the one that fits your question.",
        questions: [
          "Which playbooks do you have and what can you answer with them?",
          "Which playbooks can I not use because a tool is missing?",
        ],
      },
      {
        name: "live-check-of-a-device (playbook)",
        description:
          "Checks a device live with read-only show commands: version, interfaces, NTP, TACACS, routing protocols, routing table and spanning tree. A deep check adds the access lists and the last log lines. You confirm each card with your SSH login. The result is one table with a status per check.",
        questions: [
          "Do a live check of LAB.local.zz",
          "Check the device LAB.local.zz",
          "Do a deep check of LAB.local.zz including the access lists and the logging.",
        ],
      },
      {
        name: "interface-errors-of-a-device (playbook)",
        description:
          "Checks whether a device has interface errors or drops: runs show interfaces live (you confirm the card with your SSH login), parses it and reports only the interfaces with a non-zero counter, worst first, with the packet counts and error rate. Works with the device name or its IPv4 address. Counters are cumulative since the last clear.",
        questions: [
          "Do you see any interface errors on 10.1.2.3?",
          "Are there CRC errors or drops on r1?",
          "Is interface Gi0/1 on r1 clean?",
        ],
      },
      {
        name: "interface-utilization-of-a-device (playbook)",
        description:
          "Shows how busy the interfaces of a device are: runs show interfaces live (and show cdp neighbors for uplink questions, in the same card, so you confirm once with your SSH login), computes the traffic rate against each interface's capacity on the server and reports the busiest first. Works with the device name or its IPv4 address. Rates are the device's 5-minute average; a port with a neighbour is reported as neighbour-facing with the neighbour's name and type (CDP and LLDP do not say whether it is an uplink or a downlink, and phones and access points are neighbours too).",
        questions: [
          "Show me the bandwidth of 10.1.2.3.",
          "Which interface has the highest utilization on r1?",
          "Show me the uplink utilization on 10.1.2.3.",
        ],
      },
      {
        name: "overview-of-a-device (playbook)",
        description:
          "Sums up one device from Nautobot (what is documented) and Batfish (what the configuration says, with the snapshot age): role, location, interfaces, routes, management servers. Nothing is run on the device.",
        questions: [
          "Give me an overview of LAB.local.zz",
          "Tell me about LAB.local.zz",
        ],
      },
      {
        name: "where-is-this-host (playbook)",
        description:
          "Everything we know about an IP address, MAC address or host name, asked in a fixed order: client data (where it was seen), Nautobot, Batfish, ACI and DNS. One table shows what each source says and how old it is.",
        questions: [
          "Show me all informations about the IP address 192.168.180.2",
          "What data do you have from 192.168.180.2",
          "Where is the MAC address AA:BB:CC:00:01:00?",
        ],
      },
      {
        name: "where-is-this-network (playbook)",
        description:
          "Where a network (prefix) is configured: Nautobot (documented), Batfish (interfaces and routes of the snapshot), the git config backups (every device in one search) and ACI. One table shows what each source says and how old it is.",
        questions: [
          "Where is the prefix 192.168.178.0/24 configured?",
          "Where do you see the network 192.168.178.0/24?",
        ],
      },
      {
        name: "neighbors-of-a-device (playbook)",
        description:
          "What a device is connected to: CDP and LLDP neighbours (layer 2) and routing neighbours (layer 3), compared with Nautobot cabling and the Batfish model.",
        questions: [
          "What is core1 connected to?",
          "Which OSPF neighbours does core1 have?",
        ],
      },
      {
        name: "config-backup-or-live (playbook)",
        description:
          "Reads the running or startup configuration from the git backup, with its age, or live from the device when you ask for it.",
        questions: [
          "Get the running config of r1.",
          "What is configured on r1?",
        ],
      },
      {
        name: "learn-ospf-of-a-device / learn-bgp-of-a-device (playbooks)",
        description:
          "Reads the full OSPF or BGP state of one device (process, areas, interfaces, neighbours, database or sessions and prefixes) with a set of reviewed commands you confirm once.",
        questions: ["Learn OSPF of r1.", "Show me the BGP state of r1."],
      },
      {
        name: "compare-with-baseline (playbook)",
        description:
          "Compares a device with its pyATS baseline by reading the result of a Compare Snapshot workflow run.",
        questions: ["What changed on r1 since the baseline?"],
      },
      {
        name: "target-unreachable (playbook)",
        description:
          "Finds out why a destination is not reachable from a device, using the Batfish model: path, routes, BGP, interfaces and ACLs.",
        questions: ["Why is 10.1.2.3 not reachable from r1?"],
      },
      {
        name: "aci-where-is-it / aci-can-a-reach-b / aci-epg-reachability (playbooks)",
        description:
          "Cisco ACI: where an address lives in the fabric, whether a contract allows a flow between two hosts, and which contracts connect two EPGs.",
        questions: [
          "Where is 10.1.1.5 in ACI?",
          "Can 10.1.1.5 connect to 10.1.2.5 on tcp 443 in ACI?",
          "Which contracts connect the EPGs web and db?",
        ],
      },
      {
        name: "walk-the-network (playbook)",
        description:
          "Walks through the network from one seed device by following CDP neighbours and lists the devices Nautobot does not know (details under Workflows).",
        questions: ["Walk through the network starting at core1."],
      },
    ],
  },
  {
    id: "batfish",
    title: "Batfish (network model)",
    summary:
      "Answers come from a Batfish snapshot built from your backed-up device configurations. It is a model, not the live network. Every answer names the snapshot it used.",
    requirement: "Needs the permission to query Batfish.",
    tools: [
      {
        name: "list_batfish_networks / list_batfish_snapshots",
        description:
          "Lists the networks and their snapshots, newest first. Use it to see how old the data is or to pick another snapshot.",
        questions: [
          "How old is the data you are using?",
          "Which snapshots exist for this network?",
        ],
      },
      {
        name: "get_routes",
        description:
          "Routes of the model, with longest-prefix match for a single address.",
        questions: [
          "Which route does 10.1.2.3 use on r1?",
          "Show the static routes on r1.",
        ],
      },
      {
        name: "get_traceroute",
        description:
          "Simulates the path of a packet hop by hop, including where it is dropped and why.",
        questions: [
          "Where does a packet from r1 to 10.1.2.3 go?",
          "Why is traffic from r1 to 10.9.9.9 dropped?",
        ],
      },
      {
        name: "get_bgp_session_status",
        description:
          "BGP sessions with their status, optionally only the problems.",
        questions: [
          "Are all BGP sessions established?",
          "Which BGP sessions are not established?",
        ],
      },
      {
        name: "get_interface_properties",
        description:
          "Interface settings from the configs: address, VLAN, MTU, filters, active state, plus a summary.",
        questions: [
          "What are the interface settings of r1?",
          "Which interfaces on r1 are configured up but inactive?",
        ],
      },
      {
        name: "get_device_facts",
        description:
          "Facts from the configs: syslog, NTP, DNS, TACACS and SNMP trap servers, hostname, VRFs.",
        questions: [
          "Which devices have no NTP server configured?",
          "Which syslog servers does r1 use?",
        ],
      },
      {
        name: "list_snapshot_devices / get_ip_owners",
        description:
          "Lists the devices of a snapshot and which device and interface owns an IP address, including address conflicts.",
        questions: [
          "Which devices are in the snapshot?",
          "Who owns 10.1.2.3?",
          "Are there duplicate IP addresses in the snapshot?",
        ],
      },
      {
        name: "analyze_acl",
        description:
          "Tests one flow against one ACL or filter and shows permit or deny.",
        questions: [
          "Does the ACL EDGE-IN on r1 permit TCP 443 from 10.1.1.1 to 10.2.2.2?",
        ],
      },
      {
        name: "check_reachability",
        description:
          "Whether traffic can get from a device to a destination, with the paths found. Can ignore filters to separate a filter problem from a routing problem.",
        questions: [
          "Can r1 reach 10.2.2.2 over TCP port 22?",
          "Is the problem to 10.2.2.2 a filter or a routing problem?",
        ],
      },
      {
        name: "compare_filters / differential_reachability",
        description:
          "Compares two snapshots: ACL lines that treat a flow differently, and flows whose outcome differs.",
        questions: [
          "Which ACL lines changed between the last two snapshots?",
          "Which flows from r1 work in the old snapshot but not in the new one?",
        ],
      },
      {
        name: "get_snapshot_parse_issues",
        description:
          "What Batfish could not parse in the configs: failed or partly parsed files and unrecognised lines.",
        questions: [
          "Show me the parsing errors of the newest snapshot.",
          "Why are so many interfaces inactive?",
        ],
      },
      {
        name: "query_result / fetch_slice / diff_results",
        description:
          "Large results are stored behind a handle. These tools page through them, and compare two stored results.",
        questions: [
          "Show the next rows of that result.",
          "What changed between the routes of these two snapshots?",
        ],
      },
    ],
  },
  {
    id: "nautobot",
    title: "Nautobot (documented inventory)",
    summary:
      "Reads what is documented in Nautobot: devices, interfaces, locations, IP addresses and prefixes. It shows what is recorded, not how the network behaves.",
    requirement:
      "Needs the Nautobot read permission and a configured Nautobot source.",
    tools: [
      {
        name: "list_devices / get_device",
        description:
          "Searches devices by name, role, location, status, platform or tag, and shows one device. The interfaces of a device also show their documented MAC address, their documented cable and the device and interface at the other end.",
        questions: [
          "How many devices are in Nautobot?",
          "List the active switches in Berlin.",
          "Show the details of r1 in Nautobot.",
        ],
      },
      {
        name: "list_interfaces",
        description:
          "Interfaces of a device as documented in Nautobot, page by page, each with its documented MAC address. An interface with a documented cable also shows the device and interface at the other end of the cable, so this is how the assistant finds the neighbours of a device. Interfaces without a cable show no cable data; that means no cable is documented, not that nothing is plugged in. Cable labels need the content opt-in.",
        questions: [
          "Which interfaces of r1 are documented in Nautobot?",
          "Which devices are connected to r1 according to Nautobot?",
          "Show only the cabled interfaces of r1.",
          "What is the MAC address of Ethernet0/0 on r1 in Nautobot?",
        ],
      },
      {
        name: "list_interfaces_by_mac",
        description:
          "Finds the interface, on any device, that has a given MAC address in Nautobot. Write the address in any notation: AA:BB:CC:00:01:00, aabb.cc00.0100 or aa-bb-cc-00-01-00. Several interfaces can share one address (virtual and all-zero MAC addresses), so every match is listed. An empty answer means no interface has that MAC address documented, not that it does not exist. This is the MAC address recorded on the interface, not the MAC address table a switch has learned: to see behind which port a host sits, ask for the live table (see Live device commands). Needs the addresses opt-in.",
        questions: [
          "On which interface can I find the MAC address AA:BB:CC:00:01:00?",
          "Which device has the MAC address aabb.cc00.0100?",
        ],
      },
      {
        name: "list_ip_addresses / list_prefixes / list_namespaces",
        description: "IPAM reads: addresses, prefixes and namespaces.",
        questions: [
          "Who is 10.1.2.3 assigned to in Nautobot?",
          "Which prefixes are documented in location Berlin?",
        ],
      },
      {
        name: "get_next_free_ip",
        description:
          "Finds the next free addresses in a prefix. It only reads; nothing is reserved.",
        questions: ["What is the next free IP address in 10.1.2.0/24?"],
      },
      {
        name: "list_locations / get_location / list_location_types",
        description: "The location hierarchy and its types.",
        questions: ["Which locations exist below Germany?"],
      },
      {
        name: "list_roles / list_statuses / list_tags / list_device_types / list_platforms",
        description:
          "The vocabularies Nautobot uses, so a question can use the exact value.",
        questions: [
          "Which device roles exist?",
          "Which platforms are used in Nautobot?",
        ],
      },
      {
        name: "list_virtual_chassis / get_virtual_chassis",
        description: "Stacks and their member switches.",
        questions: [
          "Which virtual chassis exist, and how many members does each have?",
        ],
      },
      {
        name: "get_device_name_matches",
        description:
          "Finds a device under both names: the Batfish node name (config hostname) and the Nautobot full name.",
        questions: ["Which Nautobot device is the Batfish node lab?"],
      },
    ],
  },
  {
    id: "catalyst-center",
    title: "Cisco Catalyst Center (controller)",
    summary:
      "Reads Cisco Catalyst Center (also called DNAC or DNA Center), the network controller: the devices and their facts, the sites and which devices belong to a site, the health of devices and sites, and the SD-Access fabric (overlay and underlay, virtual networks, the handoffs of the border nodes to the legacy network and the transits). For a question about one device the assistant looks at Nautobot first, then checks Catalyst Center with the name, or with the IP address or serial number Nautobot shows. A device Catalyst Center does not know is reported as documented in Nautobot but not managed there. The data is the controller's last collected view, not a live command, and the scores are the controller's own numbers.",
    requirement:
      "Needs permission to read Catalyst Center sources and the inventory opt-in. If no Catalyst Center source is configured, the assistant tells you an administrator must add one. Addresses, serial numbers and the neighbour addresses of a handoff need the addresses opt-in, interface descriptions the content opt-in. The SD-Access tools answer that the controller has no SD-Access API when it has none.",
    tools: [
      {
        name: "find_catalyst_center_device",
        description:
          "Finds a device in Catalyst Center by name, management IP address or serial number and says whether the controller manages it.",
        questions: [
          "Is LAB managed by Catalyst Center?",
          "Which Catalyst Center device has the serial number FOC1234ABCD?",
        ],
      },
      {
        name: "get_catalyst_center_device_details",
        description:
          "Reads facts of one device from Catalyst Center: device record, software version, interfaces, VLANs and compliance. Device and software are the default.",
        questions: [
          "Show the Catalyst Center device details of LAB.",
          "Which software version does LAB run according to Catalyst Center?",
          "Show the interfaces and compliance status of LAB in Catalyst Center.",
        ],
      },
      {
        name: "list_catalyst_center_sites",
        description:
          "Lists the sites configured in Catalyst Center as the site hierarchy (areas, buildings, floors, for example Global/EMEA/Berlin). These are the controller's own sites, not Nautobot locations. Use the exact name in the other site questions.",
        questions: [
          "List the sites of the Catalyst Center.",
          "Which Catalyst Center sites contain Berlin?",
        ],
      },
      {
        name: "list_catalyst_center_devices",
        description:
          "Lists the devices of Catalyst Center: all managed devices, or the devices assigned to one site, sub-sites included unless you exclude them. Shows hostname, role, platform, software version and reachability; management IP and serial number need the addresses opt-in.",
        questions: [
          "Show me the devices in the DNAC.",
          "What devices are part of site Global/EMEA/Berlin?",
          "Which access switches are in the site Global/EMEA/Berlin?",
        ],
      },
      {
        name: "get_catalyst_center_device_health",
        description:
          "Reads the health of one device from Catalyst Center: overall health score, CPU and memory with their scores, communication state, HA status, maintenance mode and when the data was collected. The scores are given as the controller reports them.",
        questions: [
          "How healthy is LAB according to Catalyst Center?",
          "What are the CPU and memory scores of LAB in Catalyst Center?",
        ],
      },
      {
        name: "list_catalyst_center_site_health",
        description:
          "Shows the health of the Catalyst Center sites: average network health, number of devices, health per device role and client health, worst sites first. The controller's totals (All Sites) are shown separately. Floors are not part of this report.",
        questions: [
          "How healthy are the sites in Catalyst Center?",
          "Which sites are unhealthy?",
          "Show the health of the buildings in Catalyst Center.",
        ],
      },
      {
        name: "list_catalyst_center_fabric",
        description:
          "Says which devices are part of the SD-Access overlay or underlay. Overlay: devices with a fabric role (border, control plane, edge). Underlay: those devices plus the intermediate nodes of the fabric sites that have no fabric role. Also names the fabric sites and virtual networks. Fabric sites that could not be read completely are listed as incomplete.",
        questions: [
          "Which devices are part of the overlay network?",
          "Which devices are part of the underlay network?",
          "Which border nodes does the fabric site Global/EMEA/Berlin have?",
        ],
      },
      {
        name: "list_catalyst_center_virtual_networks",
        description:
          "Lists the SD-Access virtual networks (VRFs such as INFRA_VN) with the fabric sites each is deployed to, and their layer 2 VLANs. A network that is deployed nowhere is marked as such.",
        questions: [
          "Which virtual networks exist in Catalyst Center?",
          "Which virtual networks are deployed to the fabric site Global/EMEA/Berlin?",
        ],
      },
      {
        name: "list_catalyst_center_border_handoffs",
        description:
          "Lists the SD-Access border nodes and what each hands off to the outside (legacy) network: layer 3 handoffs to IP transits (interface, virtual network, VLAN, IP pool, local and remote address), handoffs to SD-Access transits and layer 2 handoffs. A kind that could not be read for a border is named, so the list may be partial.",
        questions: [
          "What connects the fabric to the legacy network?",
          "Which handoffs does the border node border-1 have?",
          "Which virtual networks does the border node border-1 hand off?",
        ],
      },
      {
        name: "list_catalyst_center_transits",
        description:
          "Lists the SD-Access transit networks: IP transits to the legacy or WAN side (routing protocol and AS number) and SD-Access transits that connect fabrics (multicast over the transit and the control plane devices). Which borders use a transit shows in their handoffs.",
        questions: [
          "Which transits exist in Catalyst Center?",
          "Which IP transits does the fabric have and which AS number do they use?",
        ],
      },
    ],
  },
  {
    id: "aci",
    title: "Cisco ACI (fabric)",
    summary:
      "Lists the leaf and spine switches of a Cisco ACI fabric (APIC) and reads their facts: software, health, faults, interfaces, neighbours, routes, endpoints, vPC, deployed EPGs and the contract rules a leaf enforces. For one switch the assistant looks at Nautobot first, then asks ACI. A switch ACI does not know is reported as such. The data is the APIC's current view, not a live command.",
    requirement:
      "Needs permission to read ACI sources (the viewer role does not have it). If no ACI source is configured, the assistant tells you an administrator must add one. Serial numbers and addresses need the addresses opt-in, descriptions the content opt-in.",
    tools: [
      {
        name: "list_aci_devices",
        description:
          "Lists the leaf and spine switches of the ACI fabric with node id, name, role, pod, model, software and state.",
        questions: [
          "Do you see devices in my ACI controller?",
          "Which leafs does the ACI fabric have?",
        ],
      },
      {
        name: "find_aci_device",
        description:
          "Finds a switch in ACI by name (wildcards * and ?), node id, serial number or management IP address.",
        questions: [
          "Is leaf-101 in the ACI fabric?",
          "Which ACI node has the serial number TEP-1-101?",
        ],
      },
      {
        name: "get_aci_device_details",
        description:
          "Reads facts of one ACI switch. Device and software are the default; ask for health, faults, interfaces, neighbours, routes, endpoints, vPC, EPGs or contracts when needed.",
        questions: [
          "Show the software, health and faults of leaf-101 in ACI.",
          "Which EPGs are deployed on leaf-101?",
        ],
      },
      {
        name: "find_aci_endpoint",
        description:
          "Finds where an IPv4 or MAC address was learned in the fabric: leaf, port or vPC, tenant, EPG and encap. An empty answer means the fabric has not learned it, not that it does not exist.",
        questions: [
          "Where is 10.193.101.4 in the ACI fabric?",
          "On which leaf is the MAC 45:CD:BB:C0:00:00?",
        ],
      },
      {
        name: "list_aci_endpoints",
        description:
          "Lists the endpoints (servers, VMs, devices) the fabric has learned in a tenant, application profile or EPG, with MAC, IPs, VRF, bridge domain and where each is attached. A configured EPG lists only hosts that sent traffic.",
        questions: [
          "Which servers are in the EPG web of the tenant Heroes?",
          "List the learned endpoints of the tenant SnV with an address in 10.193.0.0/16.",
        ],
      },
      {
        name: "get_aci_endpoint_history",
        description:
          "Shows when the APIC learned and last changed an endpoint and its addresses, its record on each leaf, and the newest event and fault lines that name it. The APIC keeps no move history, so this is timestamps and logs, not a timeline.",
        questions: [
          "When did the APIC learn the address 10.193.101.4?",
          "Show the history of the MAC 45:CD:BB:C0:00:00.",
        ],
      },
      {
        name: "check_aci_connectivity",
        description:
          "Checks whether the ACI contracts permit host A to connect to host B on a protocol and port. It finds both hosts' EPGs and VRFs and applies enforcement, preferred groups, vzAny and the contracts. Answers permitted, not permitted or unknown with the reason. It is contract intent, not a packet trace; ask for the leaf check and it also reads the zoning rules the leaves of both hosts program (what the hardware enforces) and compares them.",
        questions: [
          "Can 10.193.101.4 connect to 10.193.102.2 on TCP port 1433?",
          "Is ping allowed from 10.1.1.5 to 10.2.2.7 in ACI?",
          "Check on the leaves whether 10.193.101.4 may connect to 10.193.102.2 on TCP 443.",
        ],
      },
      {
        name: "list_aci_subnets",
        description:
          "Lists the gateway subnets of the fabric with tenant, VRF and bridge domain; filter by an address inside, a range, a tenant, a VRF or a bridge domain.",
        questions: [
          "Which bridge domain and VRF own 10.1.121.7 in ACI?",
          "List the ACI subnets of the tenant Heroes.",
        ],
      },
      {
        name: "search_aci_epgs",
        description:
          "Searches the application EPGs by name, tenant, application profile, bridge domain, class id or the contract they provide or consume.",
        questions: [
          "Find all ACI EPGs with db in the name.",
          "Which EPGs consume the contract sql?",
        ],
      },
      {
        name: "get_aci_epg",
        description:
          "Reads one EPG by tenant, application profile and name: bridge domain, class id and the contracts it provides and consumes. It can also list the leaves that carry the EPG.",
        questions: [
          "Which contracts does the EPG web in Save_The_Planet provide and consume?",
          "On which leaves is the EPG web in Save_The_Planet deployed?",
        ],
      },
      {
        name: "search_aci_contracts",
        description:
          "Searches contracts by name, tenant, scope, the EPG that provides or consumes them, or a protocol and port a filter entry covers.",
        questions: [
          "Which ACI contracts allow tcp/1433?",
          "Which contracts does the EPG db provide?",
        ],
      },
      {
        name: "get_aci_contract",
        description:
          "Reads one contract: scope, subjects, filter entries (protocol, ports) and the provider and consumer EPGs.",
        questions: ["Show the contract sql in the tenant common."],
      },
      {
        name: "find_aci_contracts_between",
        description:
          "Finds the contracts that connect two EPGs, in both directions. It is contract intent: it does not know vzAny, preferred groups or VRF enforcement, so it does not prove traffic is allowed.",
        questions: ["Is there a contract between the EPGs web and db?"],
      },
      {
        name: "list_aci_l3outs",
        description:
          "Lists the L3Outs with VRF, protocols, border nodes, routed interfaces and external EPGs with their subnets and contracts. Addresses need the addresses opt-in.",
        questions: [
          "Which L3Outs does the ACI fabric have?",
          "Which L3Outs use node 101?",
        ],
      },
    ],
  },
  {
    id: "config-backups",
    title: "Config backups (git)",
    summary:
      "Reads the backed-up running and startup configurations from the git repository. Instant, no SSH, but possibly older than the live device. Each answer says when the backup was committed.",
    requirement:
      "Needs the permission to read git files and the opt-in to share configuration content.",
    tools: [
      {
        name: "list_config_backups",
        description:
          "Lists the repositories that hold device configuration backups.",
        questions: ["Which config backup repositories exist?"],
      },
      {
        name: "get_config_backup",
        description:
          "Reads the running or startup configuration of one device.",
        questions: [
          "Show the running config of r1 from the backup.",
          "When was the config of r1 last backed up?",
        ],
      },
      {
        name: "get_config_section",
        description:
          "Reads one part of a backed-up configuration: a topic such as routing, ospf or bgp, or the sections that start with a given line. Works for large configs.",
        questions: [
          "Show me the routing related config part of r1.",
          "Show me the config section that begins with the line 'router ospf 100' on r1.",
        ],
      },
      {
        name: "search_config_backups",
        description:
          "Finds which devices contain a text or regular expression in their backed-up configuration.",
        questions: [
          "Which devices have snmp-server community public configured?",
          "Which devices have no ntp server line in their running config?",
        ],
      },
    ],
  },
  {
    id: "device-commands",
    title: "Live device commands",
    summary:
      "For the current state of a device. The assistant only proposes a read-only show command; nothing runs until you confirm it with a click.",
    requirement:
      "Switched on by the operator. Needs the command-execution permission and the opt-in to share content.",
    tools: [
      {
        name: "propose_device_command",
        description:
          "Proposes read-only commands for one device, which you confirm and run. Name the device by its inventory name or by its IPv4 management address (an address that is not in the inventory is refused). Ask for the output to be parsed (TextFSM, or Genie when it is available) and the result is shown as a table, with the raw output kept below it. This is also how to read the MAC address table a switch has learned.",
        questions: [
          "Run show version on r1.",
          "What is the current uptime of r1?",
          "Show the MAC address table of switch1 (show mac address-table) and find the port that learned aabb.cc00.0100.",
          "Run show ip interface brief on r1 and parse it with TextFSM.",
        ],
      },
      {
        name: "propose_ping_traceroute",
        description:
          "Proposes a ping (the default) and/or traceroute from one device to an IPv4 address, which you confirm and run. Ask for a traceroute only when you want the path. The assistant only picks the device, target, VRF and packet count; the commands for the device's platform (IOS, IOS-XE, NX-OS, IOS-XR, EOS, Junos) come from a reviewed list and are always limited in packets and time. IPv4 addresses only: no names, no IPv6, and no loopback, multicast or link-local targets.",
        questions: [
          "Can r1 reach 192.168.178.241?",
          "Ping 192.168.178.241 from r1.",
          "Run a traceroute from r1 to 192.168.178.241 in VRF MGMT.",
        ],
      },
      {
        name: "parse_command_output",
        description:
          "Parses the output of a command you already ran, without touching the device again. Genie only works if you approved Genie when you confirmed the command.",
        questions: ["Parse that output with TextFSM."],
      },
      {
        name: "summarize_interface_errors",
        description:
          "Counts the interface errors and drops in the parsed output of show interfaces and returns only the interfaces that have a non-zero counter (input and output errors, CRC, frame, overrun, abort, runts, giants, queue drops), worst first, with the packet counts and error rate. The counting is done on the server, so a device with hundreds of interfaces is no problem. Name one interface to see it even when it is clean. The counters are cumulative since the last clear, so a value above zero does not mean the problem is still happening.",
        questions: [
          "Do you see any interface errors on 10.1.2.3?",
          "Which interfaces on r1 have input errors or drops?",
          "Does Gi0/1 on r1 have CRC errors?",
        ],
      },
      {
        name: "summarize_interface_utilization",
        description:
          "Computes the traffic rate in and out, the capacity and the utilization in percent of every interface from the parsed output of show interfaces, busiest first. The arithmetic is done on the server, so a device with hundreds of interfaces is no problem. Ask for the uplinks or downlinks only and it keeps the ports that have a CDP or LLDP neighbour (it then needs show cdp neighbors in the same card). The rates are the device's 5-minute average and the percentage is relative to the interface's BW setting.",
        questions: [
          "Which interface has the highest load on r1?",
          "Show me the uplink utilization on 10.1.2.3.",
          "How much bandwidth does Gi0/1 on r1 use?",
        ],
      },
    ],
  },
  {
    id: "neighbors",
    title: "Neighbours (layer 2 and layer 3)",
    summary:
      "Which devices are attached to a device (CDP/LLDP) and which routers it exchanges routes with. Live results come from read-only commands that you confirm: the assistant picks them from a reviewed list and never writes them. For layer 3 it asks which routing protocol and VRF to look at, unless you said. The sources can differ: the live device is current, the model is as old as its snapshot, and Nautobot is documentation that may be incomplete. Missing in a source means no data, not not connected.",
    requirement:
      "Live discovery is switched on by the operator and needs the command-execution permission and the opt-in to share content. The model view needs the permission to query Batfish. The comparison with Nautobot also needs the Nautobot read permission and the addresses opt-in. Supported: Cisco IOS and IOS-XE, NX-OS, IOS-XR, Arista EOS and Junos.",
    tools: [
      {
        name: "propose_neighbor_discovery",
        description:
          "Proposes the neighbour commands for one device, which you confirm and run: CDP and LLDP neighbours (layer 2), the routing table next hops, or the adjacencies of one routing protocol (OSPF, BGP, EIGRP, IS-IS) in a VRF. It can also list the routing protocols and VRFs a device uses, so you can choose.",
        questions: [
          "Which devices are connected to r1 according to CDP and LLDP?",
          "Which routing protocols and VRFs does r1 use?",
          "Which OSPF neighbours does r1 have?",
          "Show the next hops in the routing table of r1.",
        ],
      },
      {
        name: "get_discovery_result",
        description:
          "Reads the result of a discovery you confirmed and shows the neighbours as a table: interface, neighbour, address, platform or state. It checks each neighbour against the inventory and can compare the layer 2 neighbours with the cabling documented in Nautobot, listing what is confirmed, undocumented, missing on the device or in conflict.",
        questions: [
          "Compare the live neighbours of r1 with the cabling in Nautobot.",
          "Which neighbours of r1 are not in the inventory?",
        ],
      },
      {
        name: "get_modelled_neighbors",
        description:
          "Layer 3 and routing protocol neighbours as the Batfish model sees them, without touching the device. Not live, and it has no layer 2 information.",
        questions: [
          "Which OSPF neighbours does r1 have in the model?",
          "Which routers is r1 connected to at layer 3 in the newest snapshot?",
        ],
      },
      {
        name: "get_neighbor_sources",
        description:
          "Shows which evidence exists for a device (live discovery, the model, Nautobot cabling) and what its platform supports.",
        questions: [
          "What can you tell me about the neighbours of r1, and from which sources?",
        ],
      },
    ],
  },
  {
    id: "learn",
    title: "Learn OSPF and BGP (feature learn)",
    summary:
      "Reads the whole picture of one routing protocol on a device in one go: for OSPF the process, areas, interfaces, neighbours and the link-state database; for BGP the local AS, router id, address families, every neighbour with its state and settings, and the peer templates. The assistant picks the read-only commands from a reviewed list and never writes them; nothing runs until you confirm. To see what changed, run the BGP learn twice, once now and once later, and ask the assistant to compare the two runs: it reports neighbours that were added or removed, sessions whose state changed, and sessions that flapped in between. The runs are kept for a few hours only, so compare within the same working session. For a baseline that must last longer, use a Compare Snapshot step in a workflow.",
    requirement:
      "Switched on by the operator. Needs the command-execution permission and the opt-in to share content. The tables, the neighbour detail and the comparison also need Genie: the permission to read the pyATS source, and Genie approved on the card when you confirm. Supported: Cisco IOS and IOS-XE only. Only the default VRF is read unless you name a VRF (BGP only).",
    tools: [
      {
        name: "propose_feature_learn",
        description:
          "Proposes the read-only commands that learn one feature of a device, which you confirm and run: ospf, or bgp (optionally for one VRF). The result is read from the run you confirmed; a command with nothing configured, for example no route reflector, is reported as such.",
        questions: [
          "Learn OSPF of r1.",
          "Learn BGP of r1.",
          "Learn the BGP state of r1 in the VRF BLUE.",
          "Is a BGP session down on r1?",
        ],
      },
      {
        name: "get_bgp_learn_result",
        description:
          "Shows the BGP learn you ran as one table: a row per neighbour and address family with remote AS, internal or external, state, prefixes received, up or down time, hold time and the reason of the last reset, plus the local AS and router id.",
        questions: [
          "Show the BGP neighbours of that learn as a table.",
          "Which BGP neighbours of r1 are not established?",
        ],
      },
      {
        name: "propose_bgp_neighbor_detail",
        description:
          "Proposes the read-only commands for one BGP neighbour from the learn: its policy and the total number of prefixes advertised to it and received from it. Pass the same VRF as the learn. The received count needs soft-reconfiguration inbound on the device; an error there is not a fault of the neighbour.",
        questions: [
          "Show the policy and the number of prefixes exchanged with the BGP neighbour 192.0.2.1 on r1.",
          "How many prefixes does r1 receive from 192.0.2.1?",
        ],
      },
      {
        name: "compare_bgp_learns",
        description:
          "Compares two BGP learns of the same device and scope (run it twice: now and later) and says what changed: neighbours added or removed, state changes, and flaps (the drop counter went up or the reset reason is new). Counters and uptimes are ignored. Ask for every difference to also compare the complete learned model (templates, capabilities, timers); that takes about 30 seconds.",
        questions: [
          "Compare the two BGP learns of r1 I ran, the earlier one against the later one.",
          "What changed in BGP on r1 between my two learns?",
          "Compare the two BGP learns of r1 and show every difference, including the complete learned model.",
        ],
      },
    ],
  },
  {
    id: "runs",
    title: "Workflow runs",
    summary:
      "Explains runs you may see: what happened, which step failed and why, and what a step produced.",
    requirement: "Needs permission to read workflow runs.",
    tools: [
      {
        name: "list_runs / get_run",
        description:
          "Finds runs and shows the status of one run with its steps.",
        questions: ["Which runs failed today?", "Why did run 123 fail?"],
      },
      {
        name: "get_step_result / get_artifact",
        description:
          "Reads the result of one step or an artifact the run produced.",
        questions: ["What did the backup step of run 123 return for r1?"],
      },
      {
        name: "list_run_events / get_run_workflow",
        description:
          "Live events inside a step and the workflow definition a run used.",
        questions: [
          "Show the events of run 123.",
          "Which workflow did run 123 use?",
        ],
      },
    ],
  },
  {
    id: "reports",
    title: "Reports",
    summary:
      "Ask for a report in plain words. The assistant builds it from Nautobot or from data your workflows collected, optionally in one of your report layouts, and shows a card. Nothing is generated until you click Generate; then you can open it and download it as PDF or as raw data (CSV).",
    requirement:
      "Needs permission to read reports (and to write reports to generate one). Reports from Nautobot also need permission to read the Nautobot source. The assistant sees report rows only if you allow the matching data in your assistant settings, but it can propose a report without seeing any row.",
    tools: [
      {
        name: "list_report_sources / list_report_datasets",
        description:
          "Shows where a report can read from (Nautobot, or the data collected by workflows) and which datasets and fields each has. No values.",
        questions: [
          "What can I put in a report?",
          "Which fields does the Nautobot device dataset have?",
        ],
      },
      {
        name: "list_report_templates",
        description:
          "Lists your organisation's report layouts and the sections each one expects, so a report can be written to fit one.",
        questions: ["Which report layouts do we have?"],
      },
      {
        name: "propose_report / preview_report_query",
        description:
          "Proposes a report with sections (a list, or a summary such as a count per group). Serial numbers and addresses are only shown to the assistant if you allow addresses; the generated report is never read by the assistant.",
        questions: [
          "Write a report that lists the serial numbers of the network devices.",
          "Write a report that lists the device type of the network devices grouped by the location.",
          "Write a report that summarizes the used software grouped by the device type.",
          "Write a report of the devices that run software 15.0.0.",
        ],
      },
    ],
  },
  {
    id: "file-compare",
    title: "Compare a file with Nautobot",
    summary:
      "Compares one column of a CSV file in a git repository with a field of the Nautobot devices (serial number, name, primary IPv4 address, location or software version) and finds what is on only one side: values in the file that no device has, and device values that are not in the file. The server does the comparison. The assistant only gets the counts and never sees a serial number or any other value; you see both lists in a card in the chat, and a long result has a Download CSV button. Name the file (a path such as export/compare.csv, or just compare.csv), the repository if there is more than one, the column and what to compare it with. The columns are separated by a semicolon unless you say otherwise. Say 'contains' if the Nautobot value only has to contain the file value, ask to ignore upper and lower case, or limit the devices to a location, role, status or tag.",
    requirement:
      "Needs permission to read git files and to read the Nautobot source. The repository must have the category CSV files (or CSV exports) in Settings, Git Repositories. No data opt-in is needed, because the assistant does not read the values. Up to 5000 devices are compared at once; with more, the assistant asks you to narrow them with a filter.",
    tools: [
      {
        name: "compare_file_with_nautobot",
        description:
          "Compares a column of a CSV file with a Nautobot device field and shows both differences in a card with a CSV download. A file name that exists in several folders is reported with its paths so you can pick one.",
        questions: [
          'Compare the file export/compare.csv in the git repository "gitea" with Nautobot. Use the column "serial" of the file and compare it with the serial number of the devices in Nautobot (exact match). I want to see the rows of the file whose serial number is not in Nautobot.',
          "Which serial numbers in compare.csv are missing in Nautobot, and which devices in Nautobot are missing in the file? Only the devices in Berlin.",
          "Compare the column hostname of devices.csv with the device names in Nautobot, ignoring upper and lower case.",
        ],
      },
      {
        name: "list_file_repositories",
        description:
          "Lists the git repositories that hold CSV files you can compare (category CSV files or CSV exports).",
        questions: ["Which repositories hold CSV files I can compare?"],
      },
      {
        name: "compare-file-with-nautobot (playbook)",
        description:
          "Collects what the comparison needs (file, repository, column, Nautobot field, match mode, scope), makes one comparison and reports the counts, the warnings (duplicates, devices without a value) and what was not checked. The lists themselves are in the card.",
        questions: [
          "Which devices in Nautobot are missing from the file compare.csv? Compare the serial numbers.",
        ],
      },
    ],
  },
  {
    id: "workflows",
    title: "Released workflows",
    summary:
      "An administrator can release a workflow for Ask the Net. The assistant describes it and proposes a run; the run starts as you after you confirm.",
    requirement:
      "Needs permission to execute workflows. Only released workflows you may run are listed.",
    tools: [
      {
        name: "list_released_workflows / describe_workflow",
        description:
          "Lists the released workflows and describes what one does and what it needs.",
        questions: [
          "Which workflows can you start for me?",
          "What does the interface backup workflow do?",
        ],
      },
      {
        name: "propose_workflow_run / get_run_result",
        description:
          "Proposes a run with the inputs you give, then reads the designated result.",
        questions: [
          "Run the config backup workflow for r1.",
          "What was the result of the run I just started?",
        ],
      },
      {
        name: "walk-the-network (playbook)",
        description:
          "Walks through the network from one seed device by following CDP neighbours and compares the devices it found with Nautobot. A released workflow does the walk with your own SSH credential, inside the prefixes its releaser allowed; you confirm one card. The result lists the devices that were logged in to, the neighbours that were seen but not visited (with the reason) and the devices Nautobot does not know. Reading it needs the inventory, addresses and run content opt-ins.",
        questions: [
          "Walk through the network starting at core1.",
          "Which devices reachable from core1 are not in Nautobot?",
        ],
      },
    ],
  },
];
