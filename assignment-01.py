import socket
import random
import struct


# Domain ko DNS wale format mein convert 
def encode_domain(domain):
    parts = domain.split(".")
    result = b""

    for part in parts:
        result += bytes([len(part)])
        result += part.encode()

    result += b"\x00"
    return result


# Response mein domain name ko skip 
def skip_name(data, pos):
    while True:
        length = data[pos]

        # Agar 0 hai to name khatam
        if length == 0:
            pos += 1
            break

        # DNS pointer mila hai
        if (length & 0xC0) == 0xC0:
            pos += 2
            break

        pos += length + 1

    return pos


# DNS query banata hai
def make_query(domain):

    # Random transaction ID
    transaction_id = random.randint(0, 65535)

    # Recursion desired
    flags = 0x0100

    # Sirf 1 question hai
    qdcount = 1

    # Query mein answers nahi hote
    ancount = 0
    nscount = 0
    arcount = 0

    # DNS header banaya
    header = struct.pack(
        "!HHHHHH",
        transaction_id,
        flags,
        qdcount,
        ancount,
        nscount,
        arcount
    )

    # Domain name
    name = encode_domain(domain)

    # Type 1 = A record
    # Class 1 = Internet
    question = name + struct.pack("!HH", 1, 1)

    return header + question, transaction_id


# DNS server ka response read karta hai
def read_response(data, transaction_id, domain):

    # Header kam az kam 12 bytes ka hota hai
    if len(data) < 12:
        print("Invalid DNS response.")
        return

    # Header se information nikal rahe hain
    response_id, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        "!HHHHHH", data[:12]
    )

    print("\n========== DNS RESPONSE ==========")
    print("Transaction ID:", response_id)
    print("Query Name:", domain)
    print("Query Type: A (IPv4)")
    print("Number of Answers:", ancount)

    # Transaction ID check
    if response_id != transaction_id:
        print("Warning: Transaction ID match nahi kar rahi.")

    # Response code check
    rcode = flags & 15

    if rcode == 0:
        print("Status: NOERROR")
    elif rcode == 3:
        print("Status: NXDOMAIN - Domain nahi mila")
    elif rcode == 2:
        print("Status: SERVFAIL - DNS server problem")
    else:
        print("Status: Error code", rcode)

    # Important flags
    rd = (flags >> 8) & 1
    ra = (flags >> 7) & 1
    aa = (flags >> 10) & 1

    print("Recursion Desired:", rd)
    print("Recursion Available:", ra)
    print("Authoritative Answer:", aa)

    # Header ke baad question start hota hai
    pos = 12

    # Question section skip karna hai
    for i in range(qdcount):
        pos = skip_name(data, pos)

        # QTYPE aur QCLASS skip
        pos += 4

    print("\n========== ANSWER RECORDS ==========")

    found = False

    # Answer records read kar rahe hain
    for i in range(ancount):

        # Name skip
        pos = skip_name(data, pos)

        # Record ki basic information
        record_type, record_class, ttl, length = struct.unpack(
            "!HHIH",
            data[pos:pos + 10]
        )

        pos += 10

        # A record ka type 1 hota hai
        if record_type == 1 and length == 4:

            # 4 bytes ko IPv4 address mein convert
            ip = socket.inet_ntoa(data[pos:pos + 4])

            print("Record Type: A")
            print("IPv4 Address:", ip)
            print("TTL:", ttl, "seconds")

            found = True

        # Next record par move
        pos += length

    if not found:
        print("No IPv4 address found.")

    print("===================================")


# Main function
def main():

    print("===================================")
    print("       SIMPLE DNS QUERY PROGRAM")
    print("===================================")

    # User se DNS server lena
    dns_server = input(
        "Enter DNS Server IP (example 8.8.8.8): "
    ).strip()

    while True:

        # Domain lena
        domain = input(
            "\nEnter domain name (exit to quit): "
        ).strip()

        # Program band karna
        if domain.lower() == "exit":
            print("Program ended.")
            break

        # Basic domain check
        if "." not in domain:
            print("Invalid domain name.")
            continue

        try:

            # UDP socket create
            sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            # 5 seconds ka timeout
            sock.settimeout(5)

            # DNS query create
            query, transaction_id = make_query(domain)

            print("\nSending DNS query...")
            print("DNS Server:", dns_server)
            print("Port: 53")

            # DNS server ko query bhejna
            sock.sendto(
                query,
                (dns_server, 53)
            )

            # Response receive karna
            response, address = sock.recvfrom(512)

            print("Response received from:", address[0])

            # Response ko read karna
            read_response(
                response,
                transaction_id,
                domain
            )

            sock.close()

        except socket.timeout:
            print("Error: DNS request timed out.")

        except socket.error as e:
            print("Socket error:", e)


# Program yahan se start hoga
if __name__ == "__main__":
    main()