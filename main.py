import socket
import threading
import os
import sys
import gzip
import io

ROUTES = {}
file_directory = "/tmp"  # default

def route(path_prefix):
    def decorator(func):
        ROUTES[path_prefix] = func
        return func
    return decorator

# ---------------------- Route Handlers ----------------------

@route("/")
def handle_root(request, path):
    return 200, "OK", "/"

@route("/echo/")
def handle_echo(request, path):
    return 200, "OK", path[len("/echo/"):]

@route("/user-agent")
def handle_user_agent(request, path):
    lines = request.split("\r\n")
    for line in lines:
        if line.lower().startswith("user-agent:"):
            return 200, "OK", line.split(":", 1)[1].strip()
    return 400, "Bad Request", ""

@route("/files")
def handle_files(request, path):
    filename = path[len("/files/"):]
    file_path = os.path.join(file_directory, filename)
    if os.path.isfile(file_path):
        with open(file_path, 'rb') as fp:
            contents = fp.read()
        return 200, "OK", contents
    else:
        return 404, "Not Found", b""

@route("/upload")
def handle_upload(request, path):
    print("in upload\n")
    headers, _, body = request.partition("\r\n\r\n")
    if "POST" not in headers.splitlines()[0]:
        return 405, "Method Not Allowed", "Only POST supported here"

    filename = path.split("/")[-1] or "upload.txt"
    file_path = f"{file_directory}/{filename}"
    with open(file_path, "wb") as f:
        f.write(body.encode())

    return 201, "Created", f"Saved to {file_path}"

# ---------------------- Routing Dispatcher ----------------------

def route_request(request):
    request_list = request.split()
    if len(request_list) < 2:
        return 400, "Bad Request", ""

    path = request_list[1]
    method = request_list[0]
    print(f"*************path  = {path} routes = {ROUTES}\n")

    for prefix in sorted(ROUTES.keys(), key=len, reverse=True):
        if prefix == path or path.startswith(prefix):
            if prefix == '/' and prefix != path:
                continue
            if prefix == '/files' and method == 'POST':
                return ROUTES['/upload'](request, path)
            return ROUTES[prefix](request, path)
    return 404, "Not Found", ""

# ---------------------- Encoding ----------------------

def handle_encoding(request):
    splitted = request.split("\r\n")
    for val in splitted:
        if val.lower().startswith('accept-encoding:'):
            if 'gzip' in val:
                return 'gzip'
    return ''

# ---------------------- Main Server Thread ----------------------

def handle_concurrent_server(client_socket, address):
    buffer = b""
    client_socket.settimeout(1.0)  # Optional: avoid hanging on bad clients

    try:
        while True:
            data = client_socket.recv(4096)
            if not data:
                break  # Client closed connection
            buffer += data

            while True:
                request_end = buffer.find(b"\r\n\r\n")
                if request_end == -1:
                    break  # Wait for full headers

                headers = buffer[:request_end].decode()
                content_length = 0

                for line in headers.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":")[1].strip())

                total_length = request_end + 4 + content_length
                if len(buffer) < total_length:
                    break  # Wait for full body

                # Full request received
                raw_request = buffer[:total_length]
                buffer = buffer[total_length:]  # Remove processed request

                request = raw_request.decode()
                print(f"request = {request}")
                status_code, status_message, body = route_request(request)
                length = len(body)

                headers_list = [f"HTTP/1.1 {status_code} {status_message}"]

                path = request.split()[1] if len(request.split()) >= 2 else ""
                if path.startswith("/files/") and status_code == 200:
                    headers_list.append("Content-Type: application/octet-stream")
                elif status_code in [200, 201]:
                    headers_list.append("Content-Type: text/plain")

                encoding_type = handle_encoding(request)
                if encoding_type:
                    headers_list.append(f"Content-Encoding: {encoding_type}")
                    if isinstance(body, str):
                        import gzip
                        body = gzip.compress(body.encode())
                        length = len(body)

                if status_code in [200, 201]:
                    headers_list.append(f"Content-Length: {length}")

                #headers_list.append("Connection: keep-alive")  # Optional: to be clear
                should_close = False
                if "connection: close" in request.lower():
                    headers_list.append("Connection: close")
                    should_close = True

                response_headers = "\r\n".join(headers_list) + "\r\n\r\n"

                
                if isinstance(body, bytes):
                    client_socket.sendall(response_headers.encode() + body)
                else:
                    client_socket.sendall((response_headers + body).encode())
                
                if should_close:
                    client_socket.close()
                    return


    except socket.timeout:
        pass  # Just end connection after inactivity
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client_socket.close()

# ---------------------- Main Entry ----------------------

def main():
    global file_directory

    if "--directory" in sys.argv:
        index = sys.argv.index("--directory")
        if index + 1 < len(sys.argv):
            file_directory = sys.argv[index + 1]
            print(f"Serving files from: {file_directory}")
        else:
            print("Warning: --directory flag provided but no path specified. Defaulting to /tmp.")
    else:
        print("No --directory argument provided. Defaulting to /tmp.")

    print("Server is starting...")
    server_socket = socket.create_server(("localhost", 4221), reuse_port=True)

    while True:
        client_socket, address = server_socket.accept()
        thread = threading.Thread(target=handle_concurrent_server, args=(client_socket, address))
        thread.start()

if __name__ == "__main__":
    main()
