import dns.resolver
import json
import os
import unittest
import random
import requests

TEST_IP_ENV_VAR = "TEST_IP"

# Default creds. Will need a way to override these when it changes
ADMIN_USER = "admin"
ADMIN_PASSWORD = "connectbox"
_testBaseURL = ""
# Text in the welcome template
WELCOME_TEMPLATE_TEXT_SAMPLE = "<TITLE>Connected to ConnectBox Wifi</TITLE>"
# Corresponds to the 302 in the nginx default vhost config
FINAL_302_PAGE_SUFFIX = "to-hostname"


def getTestTarget():
    try:
        return os.environ[TEST_IP_ENV_VAR]
    except KeyError:
        error_msg = "Set the %s environment variable" % \
            (TEST_IP_ENV_VAR,)
        raise RuntimeError(error_msg)


def getTestBaseURL():
    """Gets the ConnectBox base URL, solely from the IP address

    1. Deregister client to ensure correct state
    2. First request to register client
    3. Subsequent request to receive 302 back to nginx
    4. Final request that uses nginx to 302 to ConnectBox vhost
    5. Deregister client to ensure correct state for subsequent requests

    Steps 3 & 4 happen in one requests.get because it follow redirects
    """

    global _testBaseURL
    if not _testBaseURL:
        # Deregister
        r = requests.delete("http://%s/_authorised_clients" %
                            (getTestTarget(),))
        r.raise_for_status()
        # Register (no redirects given)
        r = requests.post("http://%s/_authorised_clients" %
                          (getTestTarget(),),)
        r.raise_for_status()
        # bounce through the 302, and retrieve the base connectbox page
        r = requests.get("http://%s/_redirect_to_connectbox" %
                         (getTestTarget(),),)
        r.raise_for_status()
        # and this is the ConnectBox base URL that we want
        _testBaseURL = r.url
        # Deregister the client, so that the test case that triggered
        #  this request starts with a clean slate
        r = requests.delete("http://%s/_authorised_clients" %
                            (getTestTarget(),))
        r.raise_for_status()
    return _testBaseURL


def getAdminBaseURL():
    return getTestBaseURL() + "/admin"


def getAdminAuth():
    return requests.auth.HTTPBasicAuth(ADMIN_USER, ADMIN_PASSWORD)


class ConnectBoxBasicTestCase(unittest.TestCase):

    def testContentResponseType(self):
        # URLs under content should return json
        r = requests.get("%s/content/" % (getTestBaseURL(),))
        r.raise_for_status()
        self.assertIsInstance(r.json(), list)

    def testAdminNeedsAuth(self):
        r = requests.get("%s/" % (getAdminBaseURL(),))
        # No raise_for_status because we're checking for a 401
        self.assertEqual(r.status_code, 401)

    def testAdminNoTrailingSlashRequired(self):
        r = requests.get("%s" % (getAdminBaseURL(),), auth=getAdminAuth())
        r.raise_for_status()
        self.assertIn("ConnectBox Admin Dashboard", r.text)

    def testAdminPageTitle(self):
        r = requests.get("%s/" % (getAdminBaseURL(),), auth=getAdminAuth())
        r.raise_for_status()
        self.assertIn("ConnectBox Admin Dashboard", r.text)

    def testTextInDocumentTitle(self):
        r = requests.get("%s/" % (getTestBaseURL(),))
        r.raise_for_status()
        self.assertIn("<title>ConnectBox</title>", r.text)


class ConnectBoxDNSTestCase(unittest.TestCase):
    """Behavioural tests for the dnsmasq server"""

    def setUp(self):
        """Simulate first connection

        Make sure the ConnectBox doesn't think the client has connected
        before, so we can test captive portal behaviour
        """
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = [getTestTarget()]

    def testBasicDNSResponse(self):
        # Test the default response
        reply = self.resolver.query('google.com')

        # Expect an A record
        self.assertEqual(dns.rdatatype.to_text(reply.rdtype), 'A')

        # ... with a single item
        self.assertEqual(len(reply.rrset.items), 1)

        # ... containing the right address
        self.assertEqual(str(reply.rrset.items[0]), '10.129.0.1')

    def testAndroidDNSResponse(self):
        # Test the special host needed for Android Captive Portal
        reply = self.resolver.query('connectivitycheck.gstatic.com')

        # Expect an A record
        self.assertEqual(dns.rdatatype.to_text(reply.rdtype), 'A')

        # ... with a single item
        self.assertEqual(len(reply.rrset.items), 1)

        # ... containing a non-private IP
        self.assertEqual(str(reply.rrset.items[0]), '172.217.3.174')


class ConnectBoxDefaultVHostTestCase(unittest.TestCase):
    """Behavioural tests for the Nginx default vhost"""

    # Something that we will find in the CP welcome page
    CAPTIVE_PORTAL_SEARCH_TEXT = \
        "<TITLE>Connected to ConnectBox Wifi</TITLE>"

    def setUp(self):
        """Simulate first connection

        Make sure the ConnectBox doesn't think the client has connected
        before, so we can test captive portal behaviour
        """
        r = requests.delete("http://%s/_authorised_clients" %
                            (getTestTarget(),))
        r.raise_for_status()

    def tearDown(self):
        """Leave system in a clean state

        Make sure the ConnectBox won't think this client has connected
        before, regardless of whether the next connection is from a
        test, or from a normal browser or captive portal connection
        """
        r = requests.delete("http://%s/_authorised_clients" %
                            (getTestTarget(),))
        r.raise_for_status()

    def testNoBaseRedirect(self):
        """A hit on the index does not redirect to ConnectBox"""
        r = requests.get("http://%s" % (getTestTarget(),),
                         allow_redirects=False)
        r.raise_for_status()
        self.assertFalse(r.is_redirect)

    def testIOS9CaptivePortalResponse(self):
        """iOS9 ConnectBox connection workflow"""
        # 1. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        # This is the UA from iOS 9.2.1 but let's assume it's representative
        headers.update({"User-Agent": "CaptiveNetworkSupport-325.10.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. We provide response that indicates no internet, causing
        #   captive portal browser to be opened
        self.assertNotIn("<BODY>\nSuccess\n</BODY>", r.text)
        # 3. Device sends regular user agent request for hotspot-detect.html
        #    to serve as contents of captive portal browser window
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "Mozilla/5.0 (iPad; CPU OS 9_2_1 like"
                        " Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko)"
                        " Mobile/13D15"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. We send a welcome page, with a link to click
        self.assertIn("<a href='%s'" % (getTestBaseURL(),), r.text)
        # 5. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "CaptiveNetworkSupport-325.10.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 6. We provide response that indicates an internet connection which
        #    changes captive portal browser button to "Done" and allows the
        #    user to click on the link
        self.assertIn("<BODY>\nSuccess\n</BODY>", r.text)

    def testIOS10CaptivePortalResponse(self):
        """iOS10 ConnectBox connection workflow"""
        # 1. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        # This is the UA from iOS 10.3.1 but let's assume it's representative
        headers.update({"User-Agent": "CaptiveNetworkSupport-346.50.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. We provide response that indicates no internet, causing
        #   captive portal browser to be opened
        self.assertNotIn("<BODY>\nSuccess\n</BODY>", r.text)
        # 3. Device sends regular user agent request for hotspot-detect.html
        #    to serve as contents of captive portal browser window
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "Mozilla/5.0 (iPad; CPU OS 10_3_1 like"
                        " Mac OS X) AppleWebKit/603.1.30 (KHTML, like Gecko)"
                        " Mobile/14E304"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. We send a welcome page, but no link because 10.3.1 doesn't allow
        #    exiting of the captive portal browser by clicking on a link. We
        #    do send a text URL for cutting and pasting
        self.assertNotIn("<a href=", r.text)
        self.assertIn(getTestBaseURL(), r.text)
        # 5. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "CaptiveNetworkSupport-346.50.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 6. We provide response that indicates an internet connection which
        #    changes captive portal browser button to "Done" and allows the
        #    user to click on the link
        self.assertIn("<BODY>\nSuccess\n</BODY>", r.text)

    def testSierraCaptivePortalResponse(self):
        """MacOS 10.12 ConnectBox connection workflow

        Expected to be the same as post yosemite"""
        # 1. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        # This is the UA from OS 10.12.4 but let's assume it's representative
        headers.update({"User-Agent": "CaptiveNetworkSupport-346.50.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. Connectbox provides response that indicates no internet, causing
        #   captive portal browser to be opened
        self.assertNotIn("<BODY>\nSuccess\n</BODY>", r.text)
        # 3. Device sends regular user agent request for hotspot-detect.html
        #    to serve as contents of captive portal browser window
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X"
                        " 10_12_4) AppleWebKit/603.1.30 (KHTML, like Gecko)"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. Connectbox sends a welcome page, with a link to click
        self.assertIn("<a href='%s'" % (getTestBaseURL(),), r.text)
        # 5. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        headers.update({"User-Agent": "CaptiveNetworkSupport-346.50.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 6. Connectbox provides response that indicates an internet
        #    connection which changes captive portal browser button to "Done"
        #    and allows the user to click on the link
        self.assertIn("<BODY>\nSuccess\n</BODY>", r.text)

    def testAndroid5CaptivePortalResponse(self):
        """Android 5 ConnectBox connection workflow

        We don't advertise internet access to Android devices.
        """
        # Strictly this should be requesting
        #  http://clients3.google.com/generate_204 but answering requests for
        #  that site requires DNS mods, which can't be assumed for all
        #  people running these tests, so let's just poke for the page using
        #  the IP address of the server so we hit the default server, where
        #  this 204 redirection is active.
        # 1. Device sends generate_204 request
        headers = requests.utils.default_headers()
        # This is the UA from a Lenovo junk Android 5 tablet, but let's assume
        #  that it's representative of over Android 5 (lollipop) devices
        headers.update({"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 5.0.1; "
                        "Lenovo TB3-710F Build/LRX21M)"})
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. Connectbox replies indicating no internet access
        self.assertEqual(r.status_code, 200)
        # 3. Device send another generate_204 request within a few seconds
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. Connectbox replies that internet access is still not available
        self.assertEqual(r.status_code, 200)
        # 5. On receipt of something other than a 204, the device shows a
        #    "Sign-in to network" notification.
        #    We assume that the user responds to this notification, which
        #    causes the Android captive portal browser to send a request
        #    to the generate_204 URL
        headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 5.0.1; "
                        "Lenovo TB3-710F Build/LRX21M; wv) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Version/4.0 Chrome/45.0.2454.95 "
                        "Safari/537.36"})
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 6. Connectbox provides a response with a text-URL and still
        #    indicating that internet access isn't available
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)
        # We don't want to show URLs in this captive portal browser
        self.assertNotIn("href=", r.text.lower())

    @unittest.skip("Some android 6 devices have different workflow")
    def testAndroid6CaptivePortalResponse(self):
        """Android 6 ConnectBox connection workflow
        """
        # Strictly this should be requesting
        #  http://clients3.google.com/generate_204 but answering requests for
        #  that site requires DNS mods, which can't be assumed for all
        #  people running these tests, so let's just poke for the page using
        #  the IP address of the server so we hit the default server, where
        #  this 204 redirection is active.
        # 1. Device sends generate_204 request
        headers = requests.utils.default_headers()
        # This is the UA from a Nexus 7 phone, but let's assume that it's
        #  representative of over Android 6 (marshmallow) devices
        headers.update({"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; "
                        "Nexus 7 Build/MOB30X)"})
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. Connectbox provides response that indicates no internet
        #    but schedules access to be granted after
        #    ANDROID_V6_REGISTRATION_DELAY_SECS. We don't want to wait that
        #    long during a test run, so we'll just assume that it works.
        self.assertEqual(r.status_code, 200)
        # 3. Device send another generate_204 request within a few seconds
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. Connectbox replies that internet access is still not available
        self.assertEqual(r.status_code, 200)
        # 5. On receipt of a 200 i.e. internet access unavailable, the device
        #    shows a "Sign-in to network" notification (until a 204 is
        #    received)
        #    We assume that the user responds to this notification, which
        #    causes the Android captive portal browser to send a request
        #    to the generate_204 URL
        headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; "
                        "Nexus 7 Build/MOB30X; wv) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Version/4.0 Chrome/61.0.3163.98 "
                        "Safari/537.36"})
        r = requests.get("http://%s/generate_204" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 6. Connectbox provides a response with a text-URL
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)
        # We don't want to show URLs in this captive portal browser
        self.assertNotIn("href=", r.text.lower())

    def testUnrecognisedRequestsDoNotAuthoriseClient(self):
        """We don't want to authorise clients when they request an unknown URL

        We do want to provide a redirect. Based on iOS workflow, given that's
        one of the few where we actually store state.
        """
        # 1. Device sends wispr hotspot-detect.html request
        headers = requests.utils.default_headers()
        # This is the UA from iOS 10.3.1 but let's assume it's representative
        headers.update({"User-Agent": "CaptiveNetworkSupport-346.50.1 wispr"})
        r = requests.get("http://%s/hotspot-detect.html" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 2. We provide response that indicates no internet, causing
        #   captive portal browser to be opened
        self.assertNotIn("<BODY>\nSuccess\n</BODY>", r.text)
        # 3. Request another URL from the site, but one that isn't a valid
        #    flask route i.e. testing unknown file workflow
        r = requests.get("http://%s/favicon.ico" %
                         (getTestTarget(),), headers=headers)
        r.raise_for_status()
        # 4. Connectbox should still provide a response indicating no
        #    internet
        self.assertNotIn("<BODY>\nSuccess\n</BODY>", r.text)

    def testAndroid7FallbackCaptivePortalResponse(self):
        """Return a 204 status code to bypass Android captive portal login"""
        # Strictly this should be requesting
        #  http://clients3.google.com/gen_204 but it's easier to test, and
        #  functionally equivalent to send to the default vhost
        r = requests.get("http://%s/gen_204" % (getTestTarget(),))
        r.raise_for_status()
        # 2. Connectbox provides response that indicates no internet
        #    We also make sure we get a captive portal page on this
        #    request.
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)
        # 3. Device tries again
        r = requests.get("http://%s/gen_204" % (getTestTarget(),))
        r.raise_for_status()
        # 4. Connectbox provides response that indicates no internet
        #    confirming that the device is not being registered
        #    We also make sure we get a captive portal page on this
        #    request.
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)

    def testWindowsCaptivePortalResponse(self):
        """Bounce Windows to the captive portal welcome page"""
        r = requests.get("http://%s/ncsi.txt" % (getTestTarget(),))
        r.raise_for_status()
        # Make sure we get a portal page
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)
        r = requests.get("http://%s/ncsi.txt" % (getTestTarget(),))
        r.raise_for_status()
        # Make sure we still get a portal page on this subsequent request
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)

    def testAmazonKindleFireCaptivePortalResponse(self):
        """Bounce Kindle Fire to the captive portal welcome page"""
        r = requests.get("http://%s/kindle-wifi/wifistub.html" %
                         (getTestTarget(),))
        r.raise_for_status()
        # Make sure we get a portal page
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)
        r = requests.get("http://%s/kindle-wifi/wifistub.html" %
                         (getTestTarget(),))
        r.raise_for_status()
        # Make sure we still get a portal page on this subsequent request
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.CAPTIVE_PORTAL_SEARCH_TEXT, r.text)

    def testUnknownLocalPageResponse(self):
        """
        An unregistered local page hit does not redirect to ConnectBox content
        """
        r = requests.get("http://%s/unknown_local_page" % (getTestTarget(),),
                         allow_redirects=False)
        r.raise_for_status()
        self.assertFalse(r.is_redirect)

    def testUnknownNonLocalPageResponse(self):
        """
        A remote page hit does not redirect to ConnectBox content
        """
        s = requests.Session()
        r = s.request(
            "GET",
            "http://%s/unknown_non_local_page" % (getTestTarget(),),
            allow_redirects=False,
            headers={"Host": "non-local-host.com"},
        )
        r.raise_for_status()
        self.assertFalse(r.is_redirect)


class ConnectBoxAPITestCase(unittest.TestCase):

    ADMIN_SSID_URL = "%s/api/ssid" % (getAdminBaseURL(),)
    ADMIN_HOSTNAME_URL = "%s/api/hostname" % (getAdminBaseURL(),)
    ADMIN_STATICSITE_URL = "%s/api/staticsite" % (getAdminBaseURL(),)
    SUCCESS_RESPONSE = ["SUCCESS"]
    BAD_REQUEST_TEXT = "BAD REQUEST"

    @classmethod
    def setUpClass(cls):
        r = requests.get(cls.ADMIN_SSID_URL, auth=getAdminAuth())
        r.raise_for_status()
        cls._original_ssid = r.json()["result"][0]
        r = requests.get(cls.ADMIN_STATICSITE_URL, auth=getAdminAuth())
        r.raise_for_status()
        cls._original_staticsite = r.json()["result"][0]

    @classmethod
    def tearDownClass(cls):
        r = requests.put(cls.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": cls._original_ssid}))
        r.raise_for_status()
        r = requests.put(cls.ADMIN_STATICSITE_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": cls._original_staticsite}))
        r.raise_for_status()

    def testAdminApiSmoketest(self):
        # To catch where there is a gross misconfiguration that breaks
        #  nginx/php
        r = requests.get(self.ADMIN_HOSTNAME_URL, auth=getAdminAuth())
        r.raise_for_status()
        self.assertEqual(r.json()["code"], 0)

    def testSSIDUnchRoundTrip(self):
        r = requests.get(self.ADMIN_SSID_URL, auth=getAdminAuth())
        initial_ssid = r.json()["result"][0]
        r = requests.put(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": initial_ssid}))
        r.raise_for_status()
        self.assertEqual(self.SUCCESS_RESPONSE, r.json()["result"])
        r = requests.get(self.ADMIN_SSID_URL, auth=getAdminAuth())
        r.raise_for_status()
        final_ssid = r.json()["result"][0]
        self.assertEqual(initial_ssid, final_ssid)

    def testSetSSID(self):
        new_ssid = "ssid-%s" % (random.randint(0, 1000000000),)
        r = requests.put(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": new_ssid}))
        r.raise_for_status()
        self.assertEqual(self.SUCCESS_RESPONSE, r.json()["result"])
        r = requests.get(self.ADMIN_SSID_URL, auth=getAdminAuth())
        self.assertEqual(new_ssid, r.json()["result"][0])

    def testBadRequestOnIncorrectRequestType(self):
        # Need to use PUT not POST
        r = requests.post(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                          data=json.dumps({"value": "some_ssid"}))
        with self.assertRaises(requests.HTTPError) as cm:
            r.raise_for_status()

        self.assertEqual(cm.exception.response.status_code, 405)
        # The respons text is not that important and is framework dependent.
        #self.assertEqual(cm.exception.response.text, self.BAD_REQUEST_TEXT)

    def testBadRequestOnIncorrectDataType(self):
        # Need to use JSON encoded params
        r = requests.put(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data="value=some_ssid")
        with self.assertRaises(requests.HTTPError) as cm:
            r.raise_for_status()

        self.assertEqual(cm.exception.response.status_code, 400)
        self.assertEqual(cm.exception.response.text, self.BAD_REQUEST_TEXT)

    def testBadRequestOnIncorrectFormVariable(self):
        # Need to use 'value' not 'ssid'
        r = requests.put(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data=json.dumps({"ssid": "some_ssid"}))
        with self.assertRaises(requests.HTTPError) as cm:
            r.raise_for_status()

        self.assertEqual(cm.exception.response.status_code, 400)
        self.assertEqual(cm.exception.response.text, self.BAD_REQUEST_TEXT)

    def ssidSuccessfullySet(self, ssid_str):
        r = requests.put(self.ADMIN_SSID_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": ssid_str}))
        try:
            # This assumes there's not a better method to test whether
            #  the SSID was of a valid length...
            r.raise_for_status()
        except requests.HTTPError:
            return False

        if r.json()["result"] != self.SUCCESS_RESPONSE:
            return False

        r = requests.get(self.ADMIN_SSID_URL, auth=getAdminAuth())
        r.raise_for_status()
        # Finally, check whether it was actually set
        return r.json()["result"][0] == ssid_str

    def _testSSIDSetWithLength(self, ssid_str):
        # SSIDs have a maximum length of 32 octets
        # http://standards.ieee.org/getieee802/download/802.11-2007.pdf
        valid_ssid_length = len(ssid_str.encode("utf-8")) <= 32
        self.assertEqual(valid_ssid_length, self.ssidSuccessfullySet(ssid_str))

    def test32CharacterPlainSSIDSet(self):
        self._testSSIDSetWithLength("a" * 32)

    def test32CharacterUnicodeSSIDSet(self):
        # ENG codepoint is a 2 byte character
        self._testSSIDSetWithLength(u'\N{LATIN SMALL LETTER ENG}' * 16)

    def test33CharacterPlainSSIDSet(self):
        # This SSID set should be rejected
        self._testSSIDSetWithLength("a" * 33)

    def test33CharacterUnicodeSSIDSet(self):
        # EM DASH codepoint is a 3 byte character
        # This SSID set should be rejected
        self._testSSIDSetWithLength(u'\N{EM DASH}' * 11)

    def testStaticSiteSet(self):
        r = requests.put(self.ADMIN_STATICSITE_URL, auth=getAdminAuth(),
                         data=json.dumps({"value": "true"}))
        r.raise_for_status()
        self.assertEqual(r.json()["code"], 0)
        self.assertEqual(r.json()["result"], self.SUCCESS_RESPONSE)

class ConnectBoxChatTestCase(unittest.TestCase):
    CHAT_MESSAGES_URL = "%s/chat/messages" % (getTestBaseURL())
    CHAT_TEXT_DIRECTION_URL = "%s/chat/messages/textDirection" % (getTestBaseURL())

    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def test_get_messages(self):
        nick = "Foo"
        body = "message 1"
        text_direction = "ltr"
        req = requests.post(self.CHAT_MESSAGES_URL,
            json={"nick": nick, "body": body, "textDirection": text_direction})
        req.raise_for_status()

        response = req.json()
        self.assertTrue('result' in response)
        message = response['result']
        self.assertTrue('id' in message)
        id1 = message['id']

        body = "message 2"
        req = requests.post(self.CHAT_MESSAGES_URL,
            json={"nick": nick, "body": body, "textDirection": text_direction})
        req.raise_for_status()

        response = req.json()
        self.assertTrue('result' in response)
        message = response['result']
        self.assertTrue('id' in message)
        id2 = message['id']

        req = requests.get(self.CHAT_MESSAGES_URL)
        response = req.json()

        self.assertTrue('result' in response)
        messages = response['result']
        ids = []
        for msg in messages:
            self.assertTrue('id' in msg)
            self.assertTrue('timestamp' in msg)
            self.assertTrue('nick' in msg)
            self.assertTrue('body' in msg)
            self.assertTrue('textDirection' in msg)
            ids.append(msg['id'])

        self.assertTrue(id1 in ids)
        self.assertTrue(id2 in ids)

        req = requests.get('%s?max_id=%d' % (self.CHAT_MESSAGES_URL, (id2 - 1)))
        response = req.json()

        self.assertTrue('result' in response)
        messages = response['result']
        ids = []
        for msg in messages:
            self.assertTrue('id' in msg)
            self.assertTrue('timestamp' in msg)
            self.assertTrue('nick' in msg)
            self.assertTrue('body' in msg)
            self.assertTrue('textDirection' in msg)
            ids.append(msg['id'])

        self.assertFalse(id1 in ids)
        self.assertTrue(id2 in ids)

        req = requests.get('%s?max_id=%d' % (self.CHAT_MESSAGES_URL, id2))
        self.assertEqual(req.status_code, 204)

    def test_add_message(self):
        nick = "Foo"
        body = "message 1"
        text_direction = "ltr"
        req = requests.post(self.CHAT_MESSAGES_URL,
            json={"nick": nick, "body": body, "textDirection": text_direction})
        req.raise_for_status()

        response = req.json()
        self.assertTrue('result' in response)
        message = response['result']
        self.assertTrue('id' in message)

        id1 = message['id']

        body = "message 2"
        req = requests.post(self.CHAT_MESSAGES_URL,
            json={"nick": nick, "body": body, "textDirection": text_direction})
        req.raise_for_status()

        response = req.json()
        self.assertTrue('result' in response)
        message = response['result']
        self.assertTrue('id' in message)

        id2 = message['id']
        self.assertTrue(id2 > id1)

    def test_update_message(self):
        req = requests.put(self.CHAT_MESSAGES_URL,
            json={"nick": "Foo", "body": "message 1", "textDirection": "ltr"})

        self.assertEqual(req.status_code, 405)

    def test_expire_messages(self):
        req = requests.delete(self.CHAT_MESSAGES_URL)
        req.raise_for_status()

        response = req.json()
        self.assertTrue('result' in response)

        self.assertTrue(response['result'] >= 0)

    def text_default_text_direction(self):
        req = requests.get(self.CHAT_TEXT_DIRECTION_URL)
        req.raise_for_status()

        response = req.json()

        self.assertTrue('result' in response)
        self.assertTrue(response['result'] in ['ltr', 'rtl'])
