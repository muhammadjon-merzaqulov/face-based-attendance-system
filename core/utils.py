def get_client_ip(request):
    """
    Extracts the client IP address from the request object.
    Automatically handles Proxies/Nginx checking the HTTP_X_FORWARDED_FOR header first.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
