{
    "name": "Fixed Output Mail (Force SMTP Sender)",
    "summary": "Force outgoing emails to use the SMTP user as sender, preserving display name and ensuring Reply-To/Return-Path.",
    "version": "18.0.1.0.0",
    "author": "Numa / Contributors",
    "website": "https://github.com/numa-tech",
    "license": "LGPL-3",
    "category": "Productivity/Discuss",
    "depends": ["base", "mail"],
    "data": [
        "views/ir_mail_server_views.xml"
    ],
    "demo": [
        "demo/demo_companies.xml",
        "demo/demo_mail_servers.xml"
    ],
    "application": False,
    "installable": True,
}
