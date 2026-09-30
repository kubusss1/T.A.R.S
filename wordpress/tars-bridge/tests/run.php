<?php
/**
 * Testy czystej logiki TARS Bridge — bez WordPressa.
 * Uruchomienie: php wordpress/tars-bridge/tests/run.php  (kod wyjścia 1 przy błędzie)
 *
 * @package TARS_Bridge
 */

define( 'ABSPATH', __DIR__ . '/' );
require __DIR__ . '/../includes/class-tars-logic.php';

$GLOBALS['tars_failures'] = 0;
$GLOBALS['tars_asserts']  = 0;
$tests                    = array();

function check( $condition, $message ) {
	$GLOBALS['tars_asserts']++;
	if ( ! $condition ) {
		$GLOBALS['tars_failures']++;
		throw new RuntimeException( $message );
	}
}

function check_same( $expected, $actual, $message ) {
	check( $expected === $actual, $message . ' — oczekiwano ' . var_export( $expected, true ) . ', jest ' . var_export( $actual, true ) );
}

$ok_site = array(
	'https'          => true,
	'ssl_days'       => 90,
	'core_update'    => false,
	'plugin_updates' => array(),
	'theme_updates'  => array(),
	'php_version'    => '8.3.4',
	'debug_mode'     => false,
	'disk_free_mb'   => 50000,
	'last_cron_age'  => 600,
	'blog_public'    => true,
);

$tests['health: wszystko w porządku'] = function () use ( $ok_site ) {
	$r = TARS_Logic::evaluate_health( $ok_site );
	check_same( 'ok', $r['health'], 'health' );
	check_same( array(), $r['reasons'], 'reasons' );
};

$tests['health: ostrzeżenia (aktualizacje, SSL 15 dni, debug)'] = function () use ( $ok_site ) {
	$s                        = $ok_site;
	$s['core_update']         = true;
	$s['core_update_version'] = '6.9.1';
	$s['plugin_updates']      = array( array( 'name' => 'Akismet' ) );
	$s['ssl_days']            = 15;
	$s['debug_mode']          = true;
	$r                        = TARS_Logic::evaluate_health( $s );
	check_same( 'warning', $r['health'], 'health' );
	check( in_array( 'Dostępna aktualizacja WordPressa do wersji 6.9.1', $r['reasons'], true ), 'powód: core' );
	check( in_array( 'Wtyczki do aktualizacji: 1', $r['reasons'], true ), 'powód: wtyczki' );
	check( in_array( 'Certyfikat SSL wygasa za 15 dni', $r['reasons'], true ), 'powód: SSL' );
	check( in_array( 'Włączony tryb debugowania (WP_DEBUG)', $r['reasons'], true ), 'powód: debug' );
};

$tests['health: krytyczne (SSL wygasł, stare PHP, 5 wtyczek, mało dysku)'] = function () use ( $ok_site ) {
	$s                   = $ok_site;
	$s['ssl_days']       = -1;
	$s['php_version']    = '7.2.34';
	$s['plugin_updates'] = array_fill( 0, 5, array() );
	$s['disk_free_mb']   = 50;
	$r                   = TARS_Logic::evaluate_health( $s );
	check_same( 'critical', $r['health'], 'health' );
	check_same( 'Certyfikat SSL wygasł 1 dzień temu', $r['reasons'][0], 'krytyczne powody na początku' );
	check( in_array( 'Wtyczki do aktualizacji: 5', $r['reasons'], true ), 'powód: 5 wtyczek' );
	check( in_array( 'Krytycznie mało miejsca na dysku: 50 MB', $r['reasons'], true ), 'powód: dysk' );
};

$tests['health: SSL null, brak HTTPS, cron, noindex'] = function () use ( $ok_site ) {
	$s             = $ok_site;
	$s['ssl_days'] = null;
	$r             = TARS_Logic::evaluate_health( $s );
	check_same( 'warning', $r['health'], 'SSL null = ostrzeżenie' );
	check_same( array( 'Nie udało się sprawdzić certyfikatu SSL' ), $r['reasons'], 'powód SSL null' );

	$s                  = $ok_site;
	$s['https']         = false;
	$s['last_cron_age'] = 8 * 3600;
	$s['blog_public']   = false;
	$r                  = TARS_Logic::evaluate_health( $s );
	check( in_array( 'Strona nie działa po HTTPS', $r['reasons'], true ), 'brak HTTPS' );
	check( in_array( 'WP-Cron nie uruchamiał się od 8 godz.', $r['reasons'], true ), 'cron' );
	check( in_array( 'Strona blokuje indeksowanie przez wyszukiwarki', $r['reasons'], true ), 'noindex' );
	check_same( 7, TARS_Logic::ssl_days_left( 1000000 + 7 * 86400 + 5, 1000000 ), 'ssl_days_left' );
	check_same( -1, TARS_Logic::ssl_days_left( 1000000 - 10, 1000000 ), 'ssl_days_left po terminie' );
};

$tests['urządzenia: mobile vs desktop'] = function () {
	$iphone  = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1';
	$android = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36';
	$windows = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
	$mac     = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15';
	check_same( 'mobile', TARS_Logic::detect_device( $iphone ), 'iPhone' );
	check_same( 'mobile', TARS_Logic::detect_device( $android ), 'Android' );
	check_same( 'desktop', TARS_Logic::detect_device( $windows ), 'Windows' );
	check_same( 'desktop', TARS_Logic::detect_device( $mac ), 'Mac' );
	check_same( 'desktop', TARS_Logic::detect_device( '' ), 'pusty UA' );
};

$tests['boty: wykrywanie'] = function () {
	check( TARS_Logic::is_bot( 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' ), 'Googlebot' );
	check( TARS_Logic::is_bot( 'Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)' ), 'AhrefsBot' );
	check( TARS_Logic::is_bot( 'curl/8.5.0' ), 'curl' );
	check( TARS_Logic::is_bot( 'python-requests/2.31' ), 'python-requests' );
	check( TARS_Logic::is_bot( 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0 Safari/537.36' ), 'HeadlessChrome' );
	check( TARS_Logic::is_bot( '' ), 'pusty UA' );
	check( ! TARS_Logic::is_bot( 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' ), 'Chrome to nie bot' );
	check( ! TARS_Logic::is_bot( 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1' ), 'Safari iOS to nie bot' );
};

$tests['referrer: tylko domena'] = function () {
	check_same( 'google.com', TARS_Logic::referrer_domain( 'https://www.google.com/search?q=zrobsite', 'klient.pl' ), 'google + www' );
	check_same( 'facebook.com', TARS_Logic::referrer_domain( 'https://Facebook.com/some/path#x' ), 'wielkość liter' );
	check_same( '', TARS_Logic::referrer_domain( 'https://www.klient.pl/oferta', 'klient.pl' ), 'własna domena' );
	check_same( '', TARS_Logic::referrer_domain( 'android-app://com.google.android.gm/', '' ), 'nie-http' );
	check_same( '', TARS_Logic::referrer_domain( 'javascript:alert(1)', '' ), 'javascript:' );
	check_same( '', TARS_Logic::referrer_domain( 'https://evil.com/' . str_repeat( 'a', 600 ), '' ), 'za długi' );
	check_same( '', TARS_Logic::referrer_domain( '', '' ), 'pusty' );
};

$tests['hash odwiedzającego: stabilny w dniu, zmienny między dniami, bez IP'] = function () {
	$a = TARS_Logic::visitor_hash( '203.0.113.7', 'UA', '2026-09-30', 'sol' );
	$b = TARS_Logic::visitor_hash( '203.0.113.7', 'UA', '2026-09-30', 'sol' );
	$c = TARS_Logic::visitor_hash( '203.0.113.7', 'UA', '2026-10-01', 'sol' );
	$d = TARS_Logic::visitor_hash( '203.0.113.7', 'UA', '2026-09-30', 'inna-sol' );
	$e = TARS_Logic::visitor_hash( '203.0.113.8', 'UA', '2026-09-30', 'sol' );
	check_same( $a, $b, 'ten sam dzień' );
	check( $a !== $c, 'inny dzień' );
	check( $a !== $d, 'inna sól' );
	check( $a !== $e, 'inne IP' );
	check_same( 32, strlen( $a ), 'długość' );
	check( (bool) preg_match( '/^[0-9a-f]{32}$/', $a ), 'hex' );
	check( false === strpos( $a, '.' ), 'brak IP w hashu' );
};

$tests['zgody: normalizacja statusów'] = function () {
	check_same( 'accepted_all', TARS_Logic::normalize_consent( 'accepted' ), 'accepted' );
	check_same( 'accepted_all', TARS_Logic::normalize_consent( 'Accept All' ), 'Accept All' );
	check_same( 'accepted_all', TARS_Logic::normalize_consent( 'allow' ), 'allow (Complianz)' );
	check_same( 'accepted_all', TARS_Logic::normalize_consent( true ), 'true' );
	check_same( 'rejected', TARS_Logic::normalize_consent( 'deny' ), 'deny' );
	check_same( 'rejected', TARS_Logic::normalize_consent( 'reject-all' ), 'reject-all' );
	check_same( 'rejected', TARS_Logic::normalize_consent( false ), 'false' );
	check_same( 'custom', TARS_Logic::normalize_consent( 'custom' ), 'custom' );
	check_same( 'custom', TARS_Logic::normalize_consent( 'partial' ), 'partial' );
	check_same( null, TARS_Logic::normalize_consent( 'hacker<script>' ), 'nieznany' );
	check_same( null, TARS_Logic::normalize_consent( array( 'accepted' ) ), 'tablica' );
	check_same( null, TARS_Logic::normalize_consent( str_repeat( 'a', 100 ) ), 'za długi' );
};

$tests['ścieżki: walidacja i długość'] = function () {
	check_same( '/oferta/', TARS_Logic::sanitize_path( '/oferta/?utm_source=x#top' ), 'bez query/fragmentu' );
	check_same( null, TARS_Logic::sanitize_path( 'https://evil.com/' ), 'pełny URL' );
	check_same( null, TARS_Logic::sanitize_path( '//evil.com/x' ), 'protocol-relative' );
	check_same( null, TARS_Logic::sanitize_path( '' ), 'pusty' );
	check_same( null, TARS_Logic::sanitize_path( 123 ), 'nie string' );
	check_same( null, TARS_Logic::sanitize_path( '/' . str_repeat( 'a', 3000 ) ), 'za długi surowy' );
	check_same( 255, strlen( TARS_Logic::sanitize_path( '/' . str_repeat( 'a', 400 ) ) ), 'przycięty do 255' );
	check_same( '/ascriptalert(1)/script', TARS_Logic::sanitize_path( '/a<script>alert(1)</script>' ), 'usunięte < >' );
	check_same( 30, TARS_Logic::clamp_days( 'abc' ), 'clamp nie-liczba' );
	check_same( 365, TARS_Logic::clamp_days( 9999 ), 'clamp max' );
	check_same( 1, TARS_Logic::clamp_days( -5 ), 'clamp min' );
};

$tests['analityka: seria dzienna i procent akceptacji'] = function () {
	$series = TARS_Logic::fill_daily_series(
		array(
			array( 'day' => '2026-09-28', 'views' => '10', 'visitors' => '4' ),
			array( 'day' => '2026-09-30', 'views' => '6', 'visitors' => '3' ),
		),
		'2026-09-28',
		'2026-09-30',
		array( 'views', 'visitors' )
	);
	check_same( 3, count( $series ), 'liczba dni' );
	check_same( array( 'date' => '2026-09-29', 'views' => 0, 'visitors' => 0 ), $series[1], 'dzień bez danych = 0' );
	check_same( 10, $series[0]['views'], 'int' );

	$c = TARS_Logic::consent_summary(
		array(
			array( 'day' => '2026-09-29', 'status' => 'accepted_all', 'count' => '6' ),
			array( 'day' => '2026-09-29', 'status' => 'rejected', 'count' => '2' ),
			array( 'day' => '2026-09-30', 'status' => 'custom', 'count' => '2' ),
			array( 'day' => '2026-09-30', 'status' => 'bogus', 'count' => '99' ),
		),
		'2026-09-29',
		'2026-09-30'
	);
	check_same( 10, $c['totals']['total'], 'suma decyzji' );
	check_same( 60.0, $c['acceptance_rate'], 'procent akceptacji' );
	check_same( 2, $c['daily'][1]['custom'], 'custom dzień 2' );
	check_same( null, TARS_Logic::acceptance_rate( 0, 0 ), 'brak danych = null' );
	check_same( 33.3, TARS_Logic::acceptance_rate( 1, 3 ), 'zaokrąglenie' );
	check_same( array(), TARS_Logic::date_range( '2026-10-02', '2026-10-01' ), 'odwrócony zakres' );
};

$tests['limit żądań: stałe okno i klucz IP niezależny od UA'] = function () {
	$state = null;
	for ( $i = 0; $i < 3; $i++ ) {
		$r     = TARS_Logic::rate_limit_step( $state, 1000 + $i * 100, 3, 600 );
		$state = $r[1];
		check( $r[0], 'żądanie ' . ( $i + 1 ) . ' w limicie' );
	}
	check_same( 400, $r[2], 'TTL liczony od początku okna, nie od ostatniego żądania' );
	$r = TARS_Logic::rate_limit_step( $state, 1500, 3, 600 );
	check( ! $r[0], 'czwarte żądanie w oknie odrzucone' );
	$r = TARS_Logic::rate_limit_step( $state, 1600, 3, 600 );
	check( $r[0], 'po upływie okna licznik startuje od nowa (brak blokady przy ciągłym ruchu)' );
	check_same( array( 'n' => 1, 't' => 1600 ), $r[1], 'nowe okno' );
	$r = TARS_Logic::rate_limit_step( 5, 1000, 3, 600 );
	check( $r[0], 'stary format stanu (int) = nowe okno' );
	$a = TARS_Logic::ip_bucket( '203.0.113.7', '2026-09-30', 'sol' );
	check_same( 32, strlen( $a ), 'długość klucza IP' );
	check( $a !== TARS_Logic::visitor_hash( '203.0.113.7', '', '2026-09-30', 'sol' ), 'inny niż hash odwiedzającego' );
	check( false === strpos( $a, '203.0' ), 'brak IP w kluczu' );
};

$tests['odmiana: dzień/dni'] = function () {
	check_same( 'dzień', TARS_Logic::days_word( 1 ), '1' );
	check_same( 'dni', TARS_Logic::days_word( 2 ), '2' );
	check_same( 'dni', TARS_Logic::days_word( 0 ), '0' );
	$r = TARS_Logic::evaluate_health( array( 'ssl_days' => 1 ) );
	check_same( 'Certyfikat SSL wygasa za 1 dzień', $r['reasons'][0], 'SSL 1 dzień' );
};

$passed = 0;
foreach ( $tests as $name => $fn ) {
	try {
		$fn();
		$passed++;
		echo "[OK]   {$name}\n";
	} catch ( Throwable $e ) {
		echo "[BŁĄD] {$name}: " . $e->getMessage() . "\n";
	}
}
$total = count( $tests );
echo "\nTesty: {$passed}/{$total} zaliczone, asercje: {$GLOBALS['tars_asserts']}\n";
exit( $passed === $total ? 0 : 1 );
