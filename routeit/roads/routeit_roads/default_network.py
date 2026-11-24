"""Full Gujarat State & Granular Vadodara Urban Logistics Road Network for Route.it.

Includes:
- Detailed Vadodara urban sectors & institutions (Alkapuri, Sayajigunj, Fatehgunj, Nizampura,
  Karelibaug, Mandvi, Lalbaug / Gati Shakti Vishwavidyalaya (GSV), Pratapnagar, Raopura,
  Manjalpur, Makarpura GIDC, Tarsali, Akota, Old Padra Rd, Gotri, Subhanpura, Gorwa,
  Chhani / GSFC, Tandalja, Vasna-Bhayli, Sevasi, Harni Airport, Ajwa Rd, Waghodia Rd / L&T / Parul Univ, Sama).
- Statewide Gujarat logistics hubs & industrial corridors connected via NH-48, NE-1, NH-27, NH-47, NH-51, and SH routes.
"""

from __future__ import annotations

from routeit_roads.oracles import (
    ProfileGraphOracle,
    RoadEdge,
    RoadNode,
    SpeedInterval,
    TrafficScenarioSpec,
    haversine_distance_m,
)


def build_default_urban_road_network() -> tuple[tuple[RoadNode, ...], tuple[RoadEdge, ...]]:
    """Build a strongly connected directed road network covering granular Vadodara landmarks and all Gujarat cities."""
    nodes = (
        # --- Core 15 Vadodara Urban Nodes (preserving IDs & distances for deterministic test fixtures) ---
        RoadNode("N_DEPOT_ALKAPURI", 73.1685, 22.3106, "Alkapuri Central Logistics Hub (Vadodara)"),
        RoadNode("N_SAYAJIGUNJ", 73.1812, 22.3081, "Sayajigunj & MSU Campus (Vadodara)"),
        RoadNode("N_FATEHGUNJ", 73.1865, 22.3245, "Fatehgunj University Corridor (Vadodara)"),
        RoadNode("N_NIZAMPURA", 73.1755, 22.3360, "Nizampura North Terminal (Vadodara)"),
        RoadNode("N_KARELIBAUG", 73.2010, 22.3195, "Karelibaug East Sector (Vadodara)"),
        RoadNode("N_MANDVI", 73.2045, 22.2995, "Mandvi Old City Market (Vadodara)"),
        RoadNode("N_MANJALPUR", 73.1895, 22.2735, "Manjalpur Industrial Estate (Vadodara)"),
        RoadNode("N_AKOTA", 73.1640, 22.2940, "Akota Stadium Crossing (Vadodara)"),
        RoadNode("N_GOTRI", 73.1390, 22.3155, "Gotri Medical & Retail Hub (Vadodara)"),
        RoadNode("N_VASNA", 73.1460, 22.2885, "Vasna-Bhayli Link Road (Vadodara)"),
        RoadNode("N_SUBHANPURA", 73.1555, 22.3230, "Subhanpura & Ellora Park (Vadodara)"),
        RoadNode("N_WAGHODIA_RD", 73.2260, 22.2980, "Waghodia Road Logistics Zone (Vadodara)"),
        RoadNode("N_MAKARPURA_GIDC", 73.1945, 22.2485, "Makarpura GIDC Sector (Vadodara)"),
        RoadNode("N_SAMA", 73.1975, 22.3420, "Sama-Savli Corridor (Vadodara)"),
        RoadNode("N_OP_ROAD", 73.1590, 22.2995, "Old Padra Road Commercial (Vadodara)"),
        # --- Additional Granular Vadodara Landmarks & Campuses ---
        RoadNode("N_LALBAUG_GSV", 73.1972, 22.2836, "Gati Shakti Vishwavidyalaya (GSV / NAIR), Lalbaug, Vadodara"),
        RoadNode("N_PRATAPNAGAR", 73.2055, 22.2895, "Pratapnagar Railway Colony & Workshop, Vadodara"),
        RoadNode("N_RAOPURA", 73.1945, 22.3035, "Raopura & SSG Hospital, Vadodara"),
        RoadNode("N_LAXMI_VILAS", 73.1918, 22.2936, "Laxmi Vilas Palace & Dandia Bazar, Vadodara"),
        RoadNode("N_HARNI_AIRPORT", 73.2215, 22.3325, "Harni Airport & Golden Chokdi, Vadodara"),
        RoadNode("N_AJWA_RD", 73.2385, 22.3120, "Ajwa Road & Bapod Chokdi, Vadodara"),
        RoadNode("N_TARSALI", 73.2135, 22.2565, "Tarsali Bypass & NH-48 Junction, Vadodara"),
        RoadNode("N_GORWA", 73.1520, 22.3375, "Gorwa BIDC & Refinery Road, Vadodara"),
        RoadNode("N_CHHANI_GSFC", 73.1645, 22.3650, "Chhani, GSFC & IOCL Koyali Refinery, Vadodara"),
        RoadNode("N_TANDALJA", 73.1425, 22.2985, "Tandalja & Atladara Road, Vadodara"),
        RoadNode("N_SEVASI_BHAYLI", 73.1220, 22.3060, "Sevasi & Bhayli TP Scheme, Vadodara"),
        RoadNode("N_KALALI", 73.1620, 22.2630, "Kalali & Vadsar Bridge, Vadodara"),
        RoadNode("N_PARUL_WAGHODIA", 73.3635, 22.2887, "Parul University & Waghodia GIDC, Vadodara"),
        RoadNode("N_NANDESARI_GIDC", 73.0950, 22.4080, "Nandesari Chemical GIDC, Vadodara"),
        RoadNode("N_PADRA", 72.8935, 22.2385, "Padra Industrial Corridor, Vadodara"),
        RoadNode("N_DABHOI", 73.4125, 22.1290, "Dabhoi & Statue of Unity Approach, Vadodara"),
        # --- Central Gujarat Corridor (NE-1 / NH-48 / NH-47) ---
        RoadNode("N_ANAND", 72.9289, 22.5645, "Anand Amul Dairy & Vallabh Vidyanagar Hub"),
        RoadNode("N_NADIAD", 72.8634, 22.6916, "Nadiad Highway Logistics Hub"),
        RoadNode("N_AHMEDABAD", 72.5714, 23.0225, "Ahmedabad Central Transport Hub"),
        RoadNode("N_SANAND_GIDC", 72.3820, 22.9920, "Sanand Automotive GIDC (Ahmedabad)"),
        RoadNode("N_GANDHINAGAR", 72.6369, 23.2156, "Gandhinagar GIFT City & Sector Hub"),
        RoadNode("N_HALOL_GIDC", 73.4710, 22.5045, "Halol-Savli Industrial Estate"),
        RoadNode("N_GODHRA", 73.6143, 22.7788, "Godhra Panchmahal Junction"),
        RoadNode("N_DAHOD", 74.2561, 22.8379, "Dahod Eastern Border Hub"),
        # --- North Gujarat Corridor (NH-27 / SH-41) ---
        RoadNode("N_MEHSANA", 72.3693, 23.5880, "Mehsana GIDC & North Corridor"),
        RoadNode("N_PATAN", 72.1266, 23.8493, "Patan North Gujarat Terminal"),
        RoadNode("N_PALANPUR", 72.4346, 24.1724, "Palanpur Banaskantha Highway Hub"),
        RoadNode("N_HIMMATNAGAR", 72.9631, 23.5969, "Himmatnagar NH-48 Logistics Hub"),
        # --- South Gujarat Corridor (NH-48 / Industrial Belt) ---
        RoadNode("N_KARJAN", 73.1245, 22.0525, "Karjan NH-48 Toll & Industrial Zone"),
        RoadNode("N_BHARUCH", 72.9959, 21.7051, "Bharuch Narmada Highway Hub"),
        RoadNode("N_DAHEJ_SEZ", 72.5830, 21.7140, "Dahej PCPIR & Port SEZ"),
        RoadNode("N_ANKLESHWAR_GIDC", 73.0007, 21.6264, "Ankleshwar Chemical GIDC Hub"),
        RoadNode("N_SURAT", 72.8311, 21.1702, "Surat Textile & Diamond Logistics Hub"),
        RoadNode("N_HAZIRA_PORT", 72.6475, 21.1165, "Hazira Port & Heavy Industrial Hub (Surat)"),
        RoadNode("N_NAVSARI", 72.9520, 20.9467, "Navsari South Highway Corridor"),
        RoadNode("N_VALSAD", 72.9342, 20.5992, "Valsad Industrial Hub"),
        RoadNode("N_VAPI_GIDC", 72.9106, 20.3893, "Vapi GIDC Southern Border Hub"),
        # --- Saurashtra Corridor (NH-47 / NH-27 / NH-51) ---
        RoadNode("N_SURENDRANAGAR", 71.6370, 22.7251, "Surendranagar Saurashtra Gateway"),
        RoadNode("N_RAJKOT", 70.8022, 22.3039, "Rajkot Engineering & Metoda GIDC Hub"),
        RoadNode("N_MORBI", 70.8377, 22.8120, "Morbi Ceramic Industrial Zone"),
        RoadNode("N_JAMNAGAR", 70.0577, 22.4707, "Jamnagar Brass & Refinery Logistics Hub"),
        RoadNode("N_DWARKA", 68.9685, 22.2442, "Dwarka Western Coastal Terminal"),
        RoadNode("N_PORBANDAR", 69.6293, 21.6417, "Porbandar Port & Highway Hub"),
        RoadNode("N_JUNAGADH", 70.4579, 21.5222, "Junagadh Sorath Distribution Hub"),
        RoadNode("N_VERAVAL", 70.3629, 20.9159, "Veraval-Somnath Marine Logistics Hub"),
        RoadNode("N_BHAVNAGAR", 72.1519, 21.7645, "Bhavnagar Alang & Port Hub"),
        # --- Kutch Corridor (NH-27 / NH-41) ---
        RoadNode("N_GANDHIDHAM_KANDLA", 70.1337, 23.0753, "Gandhidham & Kandla Port Logistics Hub"),
        RoadNode("N_MUNDRA_PORT", 69.7213, 22.8395, "Mundra Port SEZ Container Terminal"),
        RoadNode("N_BHUJ", 69.6669, 23.2420, "Bhuj Kutch Regional Hub"),
    )

    nodes_map = {n.id: n for n in nodes}

    # Explicit Vadodara urban connections (preserving exact meters for existing test fixtures!)
    urban_connections = [
        ("N_DEPOT_ALKAPURI", "N_SAYAJIGUNJ", 1650, "primary", 12.5, True),
        ("N_DEPOT_ALKAPURI", "N_SUBHANPURA", 1900, "primary", 13.0, True),
        ("N_DEPOT_ALKAPURI", "N_OP_ROAD", 1550, "primary", 12.5, True),
        ("N_DEPOT_ALKAPURI", "N_AKOTA", 2050, "secondary", 11.0, True),
        ("N_SAYAJIGUNJ", "N_FATEHGUNJ", 1950, "primary", 12.0, True),
        ("N_SAYAJIGUNJ", "N_KARELIBAUG", 2400, "secondary", 11.0, True),
        ("N_SAYAJIGUNJ", "N_MANDVI", 2650, "secondary", 9.5, True),
        ("N_SAYAJIGUNJ", "N_AKOTA", 2350, "secondary", 11.0, True),
        ("N_FATEHGUNJ", "N_NIZAMPURA", 1750, "primary", 13.0, True),
        ("N_FATEHGUNJ", "N_KARELIBAUG", 1800, "secondary", 11.5, True),
        ("N_FATEHGUNJ", "N_SAMA", 2300, "primary", 13.5, True),
        ("N_NIZAMPURA", "N_SUBHANPURA", 2500, "secondary", 11.5, True),
        ("N_NIZAMPURA", "N_SAMA", 2450, "primary", 13.0, True),
        ("N_KARELIBAUG", "N_SAMA", 2600, "secondary", 11.5, True),
        ("N_KARELIBAUG", "N_MANDVI", 2300, "secondary", 9.0, False),  # One-way southbound in old city!
        ("N_MANDVI", "N_WAGHODIA_RD", 2400, "secondary", 10.5, True),
        ("N_WAGHODIA_RD", "N_KARELIBAUG", 3400, "primary", 12.5, True),
        ("N_MANDVI", "N_MANJALPUR", 3350, "primary", 12.0, True),
        ("N_AKOTA", "N_MANJALPUR", 3500, "primary", 13.0, True),
        ("N_AKOTA", "N_OP_ROAD", 950, "secondary", 11.0, True),
        ("N_OP_ROAD", "N_VASNA", 1850, "secondary", 11.5, True),
        ("N_OP_ROAD", "N_GOTRI", 2750, "primary", 12.5, True),
        ("N_SUBHANPURA", "N_GOTRI", 1950, "primary", 12.5, True),
        ("N_GOTRI", "N_VASNA", 3100, "secondary", 11.5, True),
        ("N_VASNA", "N_MANJALPUR", 4600, "primary", 13.5, True),
        ("N_MANJALPUR", "N_MAKARPURA_GIDC", 2850, "primary", 14.0, True),
        ("N_MAKARPURA_GIDC", "N_WAGHODIA_RD", 6200, "primary", 14.5, True),
    ]

    # Additional Vadodara & Gujarat links
    state_highway_links = [
        # Vadodara Local Landmark Links (Lalbaug GSV, Pratapnagar, Raopura, Harni, Chhani, etc.)
        ("N_MANJALPUR", "N_LALBAUG_GSV", 12.5),
        ("N_MANDVI", "N_LALBAUG_GSV", 11.5),
        ("N_LALBAUG_GSV", "N_PRATAPNAGAR", 11.5),
        ("N_LALBAUG_GSV", "N_LAXMI_VILAS", 11.5),
        ("N_SAYAJIGUNJ", "N_RAOPURA", 11.0),
        ("N_RAOPURA", "N_MANDVI", 10.5),
        ("N_RAOPURA", "N_LAXMI_VILAS", 11.0),
        ("N_LAXMI_VILAS", "N_AKOTA", 11.5),
        ("N_PRATAPNAGAR", "N_WAGHODIA_RD", 12.0),
        ("N_KARELIBAUG", "N_HARNI_AIRPORT", 13.0),
        ("N_SAMA", "N_HARNI_AIRPORT", 13.0),
        ("N_HARNI_AIRPORT", "N_AJWA_RD", 13.5),
        ("N_WAGHODIA_RD", "N_AJWA_RD", 13.0),
        ("N_WAGHODIA_RD", "N_PARUL_WAGHODIA", 17.5),
        ("N_MAKARPURA_GIDC", "N_TARSALI", 13.5),
        ("N_TARSALI", "N_WAGHODIA_RD", 14.0),
        ("N_MANJALPUR", "N_KALALI", 12.5),
        ("N_KALALI", "N_VASNA", 12.5),
        ("N_KALALI", "N_PADRA", 16.5),
        ("N_VASNA", "N_TANDALJA", 11.5),
        ("N_OP_ROAD", "N_TANDALJA", 11.5),
        ("N_GOTRI", "N_SEVASI_BHAYLI", 12.5),
        ("N_VASNA", "N_SEVASI_BHAYLI", 12.0),
        ("N_SUBHANPURA", "N_GORWA", 12.5),
        ("N_NIZAMPURA", "N_GORWA", 12.5),
        ("N_GORWA", "N_CHHANI_GSFC", 14.0),
        ("N_NIZAMPURA", "N_CHHANI_GSFC", 14.5),
        ("N_CHHANI_GSFC", "N_NANDESARI_GIDC", 16.5),
        ("N_PRATAPNAGAR", "N_DABHOI", 17.5),
        # Vadodara Gateway Links
        ("N_CHHANI_GSFC", "N_ANAND", 21.5),
        ("N_NIZAMPURA", "N_ANAND", 22.0),
        ("N_SAMA", "N_HALOL_GIDC", 19.5),
        ("N_MAKARPURA_GIDC", "N_KARJAN", 21.0),
        # Central & North Gujarat
        ("N_ANAND", "N_NADIAD", 22.5),
        ("N_NADIAD", "N_AHMEDABAD", 23.5),
        ("N_NIZAMPURA", "N_AHMEDABAD", 25.0),
        ("N_AHMEDABAD", "N_SANAND_GIDC", 19.5),
        ("N_AHMEDABAD", "N_GANDHINAGAR", 21.0),
        ("N_GANDHINAGAR", "N_MEHSANA", 21.0),
        ("N_GANDHINAGAR", "N_HIMMATNAGAR", 20.5),
        ("N_MEHSANA", "N_PATAN", 18.5),
        ("N_MEHSANA", "N_PALANPUR", 20.5),
        ("N_PATAN", "N_PALANPUR", 18.5),
        ("N_HALOL_GIDC", "N_GODHRA", 19.5),
        ("N_GODHRA", "N_DAHOD", 20.0),
        ("N_GODHRA", "N_HIMMATNAGAR", 19.0),
        # South Gujarat NH-48 & Coastal Links
        ("N_KARJAN", "N_BHARUCH", 22.0),
        ("N_BHARUCH", "N_DAHEJ_SEZ", 19.5),
        ("N_BHARUCH", "N_ANKLESHWAR_GIDC", 18.0),
        ("N_ANKLESHWAR_GIDC", "N_SURAT", 22.0),
        ("N_SURAT", "N_HAZIRA_PORT", 18.5),
        ("N_SURAT", "N_NAVSARI", 20.5),
        ("N_NAVSARI", "N_VALSAD", 21.0),
        ("N_VALSAD", "N_VAPI_GIDC", 20.5),
        # Saurashtra Links
        ("N_SANAND_GIDC", "N_SURENDRANAGAR", 21.0),
        ("N_AHMEDABAD", "N_BHAVNAGAR", 20.0),
        ("N_ANAND", "N_BHAVNAGAR", 19.0),
        ("N_SURENDRANAGAR", "N_RAJKOT", 21.5),
        ("N_SURENDRANAGAR", "N_MORBI", 20.5),
        ("N_RAJKOT", "N_MORBI", 20.0),
        ("N_RAJKOT", "N_JAMNAGAR", 21.0),
        ("N_RAJKOT", "N_JUNAGADH", 20.5),
        ("N_RAJKOT", "N_BHAVNAGAR", 19.5),
        ("N_JAMNAGAR", "N_DWARKA", 20.0),
        ("N_DWARKA", "N_PORBANDAR", 19.5),
        ("N_PORBANDAR", "N_JUNAGADH", 19.5),
        ("N_JUNAGADH", "N_VERAVAL", 19.5),
        ("N_VERAVAL", "N_BHAVNAGAR", 19.0),
        # Kutch Links
        ("N_MORBI", "N_GANDHIDHAM_KANDLA", 21.5),
        ("N_PATAN", "N_GANDHIDHAM_KANDLA", 21.0),
        ("N_GANDHIDHAM_KANDLA", "N_MUNDRA_PORT", 20.5),
        ("N_GANDHIDHAM_KANDLA", "N_BHUJ", 20.0),
        ("N_MUNDRA_PORT", "N_BHUJ", 19.5),
    ]

    edges: list[RoadEdge] = []
    for u, v, length_m, rclass, speed, bidir in urban_connections:
        edges.append(
            RoadEdge(
                id=f"E_{u}_TO_{v}",
                u=u,
                v=v,
                length_m=length_m,
                road_class=rclass,
                free_flow_speed_mps=speed,
            )
        )
        if bidir:
            edges.append(
                RoadEdge(
                    id=f"E_{v}_TO_{u}",
                    u=v,
                    v=u,
                    length_m=length_m,
                    road_class=rclass,
                    free_flow_speed_mps=speed,
                )
            )

    for u, v, speed_mps in state_highway_links:
        nu = nodes_map[u]
        nv = nodes_map[v]
        dist_m = int(round(haversine_distance_m(nu.lon, nu.lat, nv.lon, nv.lat) * 1.18))
        edges.append(
            RoadEdge(
                id=f"E_{u}_TO_{v}",
                u=u,
                v=v,
                length_m=dist_m,
                road_class="primary",
                free_flow_speed_mps=speed_mps,
            )
        )
        edges.append(
            RoadEdge(
                id=f"E_{v}_TO_{u}",
                u=v,
                v=u,
                length_m=dist_m,
                road_class="primary",
                free_flow_speed_mps=speed_mps,
            )
        )

    return nodes, tuple(edges)


# Rich landmark gazetteer for instant 2-3 character autocomplete across Vadodara & Gujarat
GUJARAT_LANDMARK_GAZETTEER: tuple[dict[str, object], ...] = (
    {"name": "Gati Shakti Vishwavidyalaya (GSV / NAIR), Lalbaug", "area": "Lalbaug, Manjalpur, Vadodara", "lat": 22.2836, "lon": 73.1972, "keywords": "gsv nair national academy indian railways lalbaug vishwavidyalaya university vadodara"},
    {"name": "Lalbaug Palace & Garden", "area": "Lalbaug, Vadodara", "lat": 22.2852, "lon": 73.1960, "keywords": "lalbaug garden palace manjalpur"},
    {"name": "Maharaja Sayajirao University (MSU Baroda)", "area": "Pratapgunj / Sayajigunj, Vadodara", "lat": 22.3092, "lon": 73.1818, "keywords": "msu baroda university sayajigunj"},
    {"name": "Parul University Campus", "area": "Limda, Waghodia, Vadodara", "lat": 22.2887, "lon": 73.3635, "keywords": "parul university waghodia limda"},
    {"name": "Navrachana University", "area": "Vasna-Bhayli Main Road, Vadodara", "lat": 22.2908, "lon": 73.1228, "keywords": "navrachana university bhayli vasna"},
    {"name": "GSFC University & Township", "area": "Fertilizer Nagar, Chhani, Vadodara", "lat": 22.3712, "lon": 73.1635, "keywords": "gsfc fertilizer nagar chhani"},
    {"name": "IOCL Gujarat Refinery (Koyali)", "area": "Koyali, Jawaharnagar, Vadodara", "lat": 22.3735, "lon": 73.1185, "keywords": "iocl koyali refinery jawaharnagar"},
    {"name": "L&T Knowledge City", "area": "NH-48, Ajwa-Waghodia Crossing, Vadodara", "lat": 22.3045, "lon": 73.2495, "keywords": "l&t lnt larsen toubro knowledge city nh48"},
    {"name": "Laxmi Vilas Palace", "area": "J.N. Marg, Vadodara", "lat": 22.2936, "lon": 73.1918, "keywords": "laxmi vilas palace Lukshmi"},
    {"name": "Vadodara Junction Railway Station", "area": "Alkapuri / Sayajigunj, Vadodara", "lat": 22.3108, "lon": 73.1809, "keywords": "railway station junction train baroda"},
    {"name": "Pratapnagar Railway Station & Workshop", "area": "Pratapnagar, Vadodara", "lat": 22.2895, "lon": 73.2055, "keywords": "pratapnagar railway workshop"},
    {"name": "Vadodara Airport (Harni)", "area": "Civil Aerodrome, Harni Road, Vadodara", "lat": 22.3325, "lon": 73.2215, "keywords": "airport harni flight"},
    {"name": "Inorbit Mall Vadodara", "area": "Gorwa - Subhanpura Road, Vadodara", "lat": 22.3216, "lon": 73.1653, "keywords": "inorbit mall subhanpura gorwa"},
    {"name": "Eva Mall Manjalpur", "area": "Saraswati Crossroads, Manjalpur, Vadodara", "lat": 22.2758, "lon": 73.1920, "keywords": "eva mall manjalpur"},
    {"name": "SSG Hospital (Sir Sayajirao General Hospital)", "area": "Jail Road, Raopura, Vadodara", "lat": 22.3052, "lon": 73.1912, "keywords": "ssg hospital civil raopura medical"},
    {"name": "GMERS Medical College & Hospital Gotri", "area": "Gotri Main Road, Vadodara", "lat": 22.3168, "lon": 73.1372, "keywords": "gmers gotri hospital medical"},
    {"name": "Bhailal Amin General Hospital (BAGH)", "area": "Gorwa Road, Vadodara", "lat": 22.3260, "lon": 73.1605, "keywords": "bhailal amin hospital gorwa bagh"},
    {"name": "Alkapuri RC Dutt Road Commercial Hub", "area": "Alkapuri, Vadodara", "lat": 22.3106, "lon": 73.1685, "keywords": "alkapuri rc dutt road"},
    {"name": "Race Course Circle", "area": "Race Course Road, Alkapuri, Vadodara", "lat": 22.3075, "lon": 73.1645, "keywords": "race course circle"},
    {"name": "Ellora Park & Indira Chakra", "area": "Subhanpura, Vadodara", "lat": 22.3185, "lon": 73.1575, "keywords": "ellora park subhanpura"},
    {"name": "Jetalpur Road Commercial Corridor", "area": "Alkapuri, Vadodara", "lat": 22.3038, "lon": 73.1712, "keywords": "jetalpur road alkapuri"},
    {"name": "Dandia Bazar Main Market", "area": "Dandia Bazar, Raopura, Vadodara", "lat": 22.2975, "lon": 73.1970, "keywords": "dandia bazar market"},
    {"name": "Sursagar Lake & Nyay Mandir", "area": "Mandvi / Raopura, Vadodara", "lat": 22.3008, "lon": 73.2002, "keywords": "sursagar lake nyay mandir mandvi"},
    {"name": "Tandalja Sun Pharma Road", "area": "Tandalja / Atladara, Vadodara", "lat": 22.2985, "lon": 73.1425, "keywords": "tandalja sun pharma atladara"},
    {"name": "Atladara BAPS Swaminarayan Mandir", "area": "Padra Road, Atladara, Vadodara", "lat": 22.2810, "lon": 73.1505, "keywords": "atladara baps swaminarayan padra road"},
    {"name": "Sevasi - Bhayli Canal Road", "area": "Sevasi / Bhayli, Vadodara", "lat": 22.3060, "lon": 73.1220, "keywords": "sevasi bhayli canal"},
    {"name": "Kalali & Vadsar Ring Road", "area": "Kalali, South-West Vadodara", "lat": 22.2630, "lon": 73.1620, "keywords": "kalali vadsar"},
    {"name": "Tarsali Chokdi & Bypass", "area": "Tarsali, South-East Vadodara", "lat": 22.2565, "lon": 73.2135, "keywords": "tarsali bypass nh48"},
    {"name": "Ajwa Road & Kamlanagar Lake", "area": "Ajwa Road, East Vadodara", "lat": 22.3120, "lon": 73.2385, "keywords": "ajwa road bapod"},
    {"name": "Nandesari Chemical GIDC", "area": "Nandesari, North Vadodara", "lat": 22.4080, "lon": 73.0950, "keywords": "nandesari gidc chemical"},
    {"name": "IIT Gandhinagar", "area": "Palaj, Gandhinagar, Gujarat", "lat": 23.2114, "lon": 72.6842, "keywords": "iit gandhinagar palaj"},
    {"name": "GIFT City Gandhinagar", "area": "Gandhinagar, Gujarat", "lat": 23.1645, "lon": 72.6837, "keywords": "gift city gandhinagar finance"},
    {"name": "IIM Ahmedabad", "area": "Vastrapur, Ahmedabad, Gujarat", "lat": 23.0329, "lon": 72.5363, "keywords": "iim ahmedabad vastrapur"},
    {"name": "Naroda GIDC Ahmedabad", "area": "Naroda, Ahmedabad, Gujarat", "lat": 23.0840, "lon": 72.6625, "keywords": "naroda gidc ahmedabad"},
    {"name": "Vatva GIDC Ahmedabad", "area": "Vatva, Ahmedabad, Gujarat", "lat": 22.9560, "lon": 72.6395, "keywords": "vatva gidc ahmedabad"},
    {"name": "Changodar Industrial Estate", "area": "NH-47, Ahmedabad, Gujarat", "lat": 22.9185, "lon": 72.4350, "keywords": "changodar industrial ahmedabad"},
    {"name": "SVNIT Surat", "area": "Ichchhanath, Dumas Road, Surat, Gujarat", "lat": 21.1663, "lon": 72.7833, "keywords": "svnit nit surat dumas"},
    {"name": "Sachin GIDC Surat", "area": "Sachin, Surat, Gujarat", "lat": 21.0875, "lon": 72.8690, "keywords": "sachin gidc surat"},
    {"name": "Statue of Unity (Ekta Nagar / Kevadia)", "area": "Ekta Nagar, Narmada, Gujarat", "lat": 21.8380, "lon": 73.7191, "keywords": "statue of unity kevadia ekta nagar"},
)


def build_default_traffic_scenario(
    scenario_id: str = "SCEN_URBAN_PEAK",
    kind: str = "TIME_PROFILE",
    revision: int = 1,
    base_day_epoch_s: int = 1794873600,  # 2026-11-17 00:00:00 UTC
    closed_edge_ids: frozenset[str] = frozenset(),
    edge_multipliers_override: dict[str, float] | None = None,
) -> TrafficScenarioSpec:
    """Create a realistic time-dependent traffic scenario (morning peak, midday normal, evening rush)."""
    if kind == "STATIC":
        intervals: tuple[SpeedInterval, ...] = ()
    else:
        intervals = (
            SpeedInterval(
                start_utc_s=base_day_epoch_s + 9000,
                end_utc_s=base_day_epoch_s + 19800,
                class_multipliers={"primary": 0.62, "secondary": 0.68, "residential": 0.82},
            ),
            SpeedInterval(
                start_utc_s=base_day_epoch_s + 19800,
                end_utc_s=base_day_epoch_s + 41400,
                class_multipliers={"primary": 0.90, "secondary": 0.92, "residential": 0.95},
            ),
            SpeedInterval(
                start_utc_s=base_day_epoch_s + 41400,
                end_utc_s=base_day_epoch_s + 54000,
                class_multipliers={"primary": 0.55, "secondary": 0.60, "residential": 0.78},
            ),
        )
    return TrafficScenarioSpec(
        scenario_id=scenario_id,
        name="Gujarat Time-Dependent Peak Profile" if kind != "STATIC" else "Static Free-Flow Baseline",
        revision=revision,
        horizon_start_utc_s=base_day_epoch_s - 86400,
        horizon_end_utc_s=base_day_epoch_s + 3 * 86400,
        grid_seconds=900,
        intervals=intervals,
        edge_multipliers_override=edge_multipliers_override or {},
        closed_edge_ids=closed_edge_ids,
    )


def create_default_profile_graph_oracle(
    scenario: TrafficScenarioSpec | None = None,
) -> ProfileGraphOracle:
    nodes, edges = build_default_urban_road_network()
    scen = scenario or build_default_traffic_scenario()
    return ProfileGraphOracle(
        nodes=nodes,
        edges=edges,
        scenario=scen,
        depot_node_id="N_DEPOT_ALKAPURI",
        max_snap_distance_m=85_000,
    )
