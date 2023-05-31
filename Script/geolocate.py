#!/usr/bin/env python3

"""Geolocate IP addresses with MaxMind's GeoLite2-City database.
    This script builds upon Mark Baggett's Geolocation Workshop. Its original basis and methodology is attributed to him.
    View his workshop's content here:
        https://github.com/MarkBaggett/GeoLocationNotebook
    This script references GeoLite2 data created by MaxMind, available from:
        https://www.maxmind.com
"""


import argparse
import requests
import re
from collections import defaultdict
from contextlib import closing
from pathlib import Path

import geoip2.database
import geoip2.errors


__author__ = "Jordan Linden"
__version__ = "1.0"
__status__ = "Prototype"


def parse_args():
    parser = argparse.ArgumentParser(
        prog='geolocate.py',
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser_opt = parser._action_groups.pop()
    
    parser_req = parser.add_argument_group("required arguments (either/or)")
    
    parser_req_group = parser_req.add_mutually_exclusive_group(required=True)
    parser_req_group.add_argument(
        '--ip',
        metavar='<string>',
        default=argparse.SUPPRESS,
        help='a single ip address to search for'
    )
    parser_req_group.add_argument(
        '--file',
        metavar='<file path>',
        type=Path,
        default=argparse.SUPPRESS,
        help='path to a text file containing multiple ip addresses'
    )
    
    parser._action_groups.append(parser_opt)
    
    parser.add_argument(
        '--db',
        metavar='<file path>',
        default='/var/lib/GeoIP/GeoLite2-City.mmdb',
        help='path to GeoLite2-City binary database'
    )
    
    parser.add_argument(
        '--group',
        choices=['ip_address', 'country', 'state/region', 'city'],
        default='ip_address',
        help='record attribute to group by'
    )
    
    parser.add_argument(
        '--search',
        metavar='<string>',
        default=argparse.SUPPRESS,
        help='regular expression to search for, returns only matching records'
    )
    
    parser.add_argument(
        '--filter',
        nargs='*',
        default=argparse.SUPPRESS,
        help='ip addresses to exclude from results, separated by spaces'
    )
    
    parser.add_argument(
        '--limit',
        metavar='<int>',
        type=int,
        default=0,
        help='maximum number of ip addresses to process'
    )
    
    parser.add_argument(
        '--show-missing',
        action='store_true',
        dest='show_not_found',
        default=False,
        help='display ip addresses not found in the records'
    )
    
    parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__)
    
    return parser, parser.parse_args()


def read_record(reader, ip):
    try:
        record = reader.city(ip)
    except (geoip2.errors.AddressNotFoundError, ValueError):
        record = None
    except (geoip2.errors.FileNotFoundError, geoip2.errors.PermissionError):
        raise
    
    return record


def get_records(reader, ip_list, search_pattern, filtered_ips, group_by):
    result_dict = defaultdict(lambda :[])
    unknown_ips = []
    
    for ip in ip_list:
        if ip in filtered_ips:
            continue
        
        try:
            record = read_record(reader, ip)
        except Exception:
            raise
        
        if record:
            city = record.city.name if record.city.name is not None else 'Unknown'
            state = record.subdivisions.most_specific.name \
                if record.subdivisions.most_specific.name is not None else 'Unknown'
            country_name = record.country.name if record.country.name is not None else 'Unknown'
            country_iso = f" ({record.country.iso_code})" if record.country.iso_code is not None else ''
            country_full = country_name + country_iso
            
            if search_pattern is not None:
                match_country = True if search_pattern.search(country_full) else False
                match_state = True if search_pattern.search(state) else False
                match_city = True if search_pattern.search(city) else False
                match_ip = True if search_pattern.search(ip) else False
                
                add_record = any([match_country, match_state, match_city, match_ip])
            else:
                add_record = True
            
            if not add_record:
                continue
            
            if group_by == 'country':
                result_dict[country_full].append(ip)
            elif group_by == 'state/region':
                result_dict[state + country_iso].append(ip)
            elif group_by == 'city':
                result_dict[city + country_iso].append(ip)
            else:
                latitude = record.location.latitude
                longitude = record.location.longitude
                
                if (latitude and longitude):
                    maps_url = f"https://maps.google.com/maps?q={latitude:0>3.9f},{longitude:0>3.9f}&z=15"
                else:
                    maps_url = 'Null'
                
                radius = record.location.accuracy_radius if record.location.accuracy_radius is not None else 'Null'
                
                result_dict[ip].extend([
                    f"Maps URL:   {maps_url}",
                    f"Radius(km): {radius}",
                    f"Country:    {country_full}",
                    f"State:      {state}",
                    f"City:       {city}"
                ])
        else:
            unknown_ips.append(ip)
    
    return result_dict, unknown_ips


def main():
    parser, args = parse_args()
    
    single_ip = args.ip if hasattr(args, "ip") else None
    file = args.file if hasattr(args, "file") else None
    
    group_by = args.group
    
    search_pattern = re.compile(args.search, re.IGNORECASE) if hasattr(args, "search") else None
    filtered_ips = args.filter if hasattr(args, "filter") else []
    
    if single_ip:
        ip_list = [single_ip]
    else:
        if not file.is_file():
            parser.error("file path is invalid or not found")
        if file.stat().st_size == 0:
            parser.error("file is empty")
        if args.limit < 1:
            limit = None
        else:
            limit = args.limit
        
        with file.open():
            data = file.read_text()
        
        pattern = r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
        ip_list = re.findall(pattern, data)[:limit]
    
    try:
        with geoip2.database.Reader(args.db) as reader:
            result_dict, unknown_ips = get_records(reader, ip_list, search_pattern, filtered_ips, group_by)
    except Exception as e:
        print("ERROR: ", e)
        return 2
    
    if result_dict:
        sorted_dict = dict(sorted(result_dict.items(), \
            key=lambda x: len(x[1]) if group_by in ['country', 'state/region', 'city'] else x[1][2], reverse=True))
        
        for key in sorted_dict:
            print('\n', key)
            for value in sorted_dict[key]:
                print(" "*4, value)
    else:
        print('No records found')
    
    if args.show_not_found and len(unknown_ips) > 0:
        print('\nIP addresses not found:')
        for ip in unknown_ips:
            print(" "*4, ip)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
