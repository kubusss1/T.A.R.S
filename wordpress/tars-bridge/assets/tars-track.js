/*! TARS Bridge — anonimowe odsłony i statystyki zgód cookie (bez cookies, bez IP). */
(function (w, d) {
	'use strict';

	var cfg = w.tarsBridge;
	var nav = w.navigator || {};
	if (!cfg || !cfg.hit || nav.webdriver) {
		return;
	}
	if (/bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview/i.test(nav.userAgent || '')) {
		return;
	}
	if (cfg.dnt && (nav.doNotTrack === '1' || nav.doNotTrack === 'yes' || w.doNotTrack === '1')) {
		return;
	}

	function send(url, data) {
		var body;
		try {
			body = new URLSearchParams(data);
		} catch (e) {
			return;
		}
		try {
			if (nav.sendBeacon && nav.sendBeacon(url, body)) {
				return;
			}
		} catch (e) { /* przejdź do fetch */ }
		if (w.fetch) {
			w.fetch(url, { method: 'POST', body: body, keepalive: true, credentials: 'omit' })['catch'](function () {});
		}
	}

	// ---- Odsłona -------------------------------------------------------------
	send(cfg.hit, {
		path: (w.location.pathname || '/').slice(0, 2048),
		referrer: (d.referrer || '').slice(0, 512)
	});

	// ---- Zgody cookie ----------------------------------------------------------
	if (!cfg.consent) {
		return;
	}

	var STORE_KEY = 'tars_consent_sent';
	var sent = false;
	var timer = null;

	function getCookie(name) {
		var parts = ('; ' + d.cookie).split('; ' + name + '=');
		if (parts.length < 2) {
			return null;
		}
		try {
			return decodeURIComponent(parts.pop().split(';')[0]);
		} catch (e) {
			return parts.pop().split(';')[0];
		}
	}

	function today() {
		var t = new Date();
		return t.getFullYear() + '-' + (t.getMonth() + 1) + '-' + t.getDate();
	}

	function alreadySent(status) {
		try {
			return w.sessionStorage.getItem(STORE_KEY) === today() + ':' + status;
		} catch (e) {
			return false;
		}
	}

	function markSent(status) {
		try {
			w.sessionStorage.setItem(STORE_KEY, today() + ':' + status);
		} catch (e) { /* tryb prywatny */ }
	}

	function report(status, source) {
		if (!status || sent || alreadySent(status)) {
			return;
		}
		sent = true;
		markSent(status);
		send(cfg.consent, { status: status, source: source || '' });
	}

	// Klasyfikacja listy kategorii: wszystkie tak / wszystkie nie / mieszane.
	function classify(yes, no) {
		if (yes > 0 && no === 0) {
			return 'accepted';
		}
		if (yes === 0 && no > 0) {
			return 'rejected';
		}
		return yes > 0 ? 'custom' : null;
	}

	// Complianz: cookies cmplz_<kategoria> = allow|deny.
	function complianzStatus() {
		var cats = ['preferences', 'statistics', 'marketing'];
		var yes = 0, no = 0, found = false;
		for (var i = 0; i < cats.length; i++) {
			var v = getCookie('cmplz_' + cats[i]);
			if (v === 'allow') { yes++; found = true; }
			if (v === 'deny') { no++; found = true; }
		}
		return found ? classify(yes, no) : null;
	}

	// CookieYes: cookie "cookieyes-consent" = "consent:yes,functional:no,analytics:yes,...".
	function cookieYesStatus() {
		var raw = getCookie('cookieyes-consent');
		if (!raw) {
			return null;
		}
		var map = {};
		raw.split(',').forEach(function (pair) {
			var kv = pair.split(':');
			if (kv.length === 2) { map[kv[0].trim()] = kv[1].trim(); }
		});
		if (map.action !== 'yes' && map.consent !== 'yes' && map.consent !== 'no') {
			return null;
		}
		var yes = 0, no = 0;
		['functional', 'analytics', 'performance', 'advertisement'].forEach(function (k) {
			if (map[k] === 'yes') { yes++; }
			if (map[k] === 'no') { no++; }
		});
		return classify(yes, no) || (map.consent === 'no' ? 'rejected' : null);
	}

	// Cookiebot: API window.Cookiebot.consent.
	function cookiebotStatus() {
		var cb = w.Cookiebot;
		if (!cb || !cb.consent) {
			return null;
		}
		var c = cb.consent;
		var yes = (c.preferences ? 1 : 0) + (c.statistics ? 1 : 0) + (c.marketing ? 1 : 0);
		return classify(yes, 3 - yes);
	}

	// Borlabs Cookie: cookie "borlabs-cookie" (JSON) z grupami w "consents".
	function borlabsStatus() {
		var raw = getCookie('borlabs-cookie');
		if (!raw) {
			return null;
		}
		var data;
		try { data = JSON.parse(raw); } catch (e) { return null; }
		var groups = data && data.consents ? Object.keys(data.consents) : [];
		if (!groups.length) {
			return null;
		}
		var extra = groups.filter(function (g) { return g !== 'essential'; });
		if (!extra.length) {
			return 'rejected';
		}
		return (extra.indexOf('statistics') !== -1 && extra.indexOf('marketing') !== -1) ? 'accepted' : 'custom';
	}

	var detectors = {
		complianz: complianzStatus,
		cookieyes: cookieYesStatus,
		cookiebot: cookiebotStatus,
		borlabs: borlabsStatus
	};

	// Stan przy wejściu: jeśli decyzja już zapadła wcześniej, nie liczymy jej ponownie.
	var hadDecision = {};
	Object.keys(detectors).forEach(function (k) {
		try { hadDecision[k] = !!detectors[k](); } catch (e) { hadDecision[k] = false; }
	});
	hadDecision.cookiebot = !!getCookie('CookieConsent');

	function check(source, force) {
		clearTimeout(timer);
		timer = setTimeout(function () {
			var status = null;
			try { status = detectors[source](); } catch (e) { status = null; }
			if (status && (force || !hadDecision[source])) {
				report(status, source);
			}
		}, 400);
	}

	// Complianz.
	d.addEventListener('cmplz_status_change', function () { check('complianz', true); });
	d.addEventListener('cmplz_fire_categories', function () { check('complianz', false); });

	// CookieYes (zdarzenie ze szczegółami accepted/rejected).
	d.addEventListener('cookieyes_consent_update', function (e) {
		var det = e && e.detail;
		if (det && det.accepted && det.rejected) {
			var yes = det.accepted.filter(function (c) { return c !== 'necessary'; }).length;
			report(classify(yes, det.rejected.length) || 'rejected', 'cookieyes');
		} else {
			check('cookieyes', true);
		}
	});

	// Cookiebot (zdarzenia wywoływane też przy wejściu — wtedy pomijamy zapisane wcześniej zgody).
	w.addEventListener('CookiebotOnAccept', function () {
		if (!hadDecision.cookiebot || (w.Cookiebot && w.Cookiebot.changed)) {
			check('cookiebot', true);
		}
	});
	w.addEventListener('CookiebotOnDecline', function () {
		if (!hadDecision.cookiebot || (w.Cookiebot && w.Cookiebot.changed)) {
			report('rejected', 'cookiebot');
		}
	});

	// Borlabs Cookie 2.x / 3.x.
	['borlabs-cookie-consent-saved', 'borlabs-cookie-after-consent-saved', 'borlabs-cookie-code-unblocked-after-consent'].forEach(function (ev) {
		d.addEventListener(ev, function () { check('borlabs', true); });
	});

	// Ogólne zdarzenie dla własnych banerów:
	// document.dispatchEvent(new CustomEvent('tars-consent', {detail: {status: 'accepted'|'rejected'|'custom'}}))
	d.addEventListener('tars-consent', function (e) {
		var s = e && e.detail && e.detail.status;
		if (s === 'accepted' || s === 'rejected' || s === 'custom') {
			report(s, 'generic');
		}
	});

	// Awaryjnie: obserwuj pojawienie się cookie wtyczki (gdy zdarzenie nie zadziała).
	var polls = 0;
	var poller = setInterval(function () {
		polls++;
		if (sent || polls > 120) {
			clearInterval(poller);
			return;
		}
		Object.keys(detectors).forEach(function (k) {
			if (sent || hadDecision[k] || k === 'cookiebot') {
				return;
			}
			var s = null;
			try { s = detectors[k](); } catch (e) { s = null; }
			if (s) {
				report(s, k);
			}
		});
	}, 2000);
})(window, document);
