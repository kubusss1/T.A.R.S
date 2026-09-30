<?php
/**
 * Czysta logika TARS Bridge — bez zależności od WordPressa, testowalna w gołym PHP.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Funkcje pomocnicze: ocena kondycji strony, wykrywanie urządzeń i botów,
 * domeny odsyłaczy, anonimowy hash odwiedzającego, normalizacja zgód.
 */
final class TARS_Logic {

	const HEALTH_OK       = 'ok';
	const HEALTH_WARNING  = 'warning';
	const HEALTH_CRITICAL = 'critical';

	const CONSENT_ACCEPTED = 'accepted_all';
	const CONSENT_REJECTED = 'rejected';
	const CONSENT_CUSTOM   = 'custom';

	/** PHP poniżej tej wersji = krytycznie (brak jakiegokolwiek wsparcia). */
	const PHP_CRITICAL_BELOW = '7.4';
	/** PHP poniżej tej wersji = ostrzeżenie (koniec wsparcia bezpieczeństwa). */
	const PHP_WARNING_BELOW = '8.2';

	const SSL_CRITICAL_DAYS = 7;
	const SSL_WARNING_DAYS  = 21;

	const DISK_CRITICAL_MB = 200;
	const DISK_WARNING_MB  = 1024;

	const PLUGIN_UPDATES_CRITICAL = 5;

	const CRON_WARNING_SECONDS = 21600; // 6 godzin.

	const MAX_PATH_LENGTH      = 255;
	const MAX_RAW_PATH_LENGTH  = 2048;
	const MAX_REFERRER_LENGTH  = 512;
	const MAX_DOMAIN_LENGTH    = 191;

	/**
	 * Ocena kondycji strony na podstawie zebranych danych.
	 *
	 * Oczekiwane klucze (wszystkie opcjonalne):
	 * https (bool), ssl_days (int|null), core_update (bool), core_update_version (string),
	 * plugin_updates (array), theme_updates (array), php_version (string),
	 * debug_mode (bool), debug_display (bool), disk_free_mb (int|null),
	 * last_cron_age (int|null, sekundy), blog_public (bool).
	 *
	 * @param array $s Dane statusu.
	 * @return array{health:string,reasons:array<int,string>}
	 */
	public static function evaluate_health( array $s ) {
		$critical = array();
		$warning  = array();

		$https    = isset( $s['https'] ) ? (bool) $s['https'] : true;
		$ssl_days = array_key_exists( 'ssl_days', $s ) ? $s['ssl_days'] : null;

		if ( ! $https ) {
			$warning[] = 'Strona nie działa po HTTPS';
		} elseif ( null === $ssl_days ) {
			$warning[] = 'Nie udało się sprawdzić certyfikatu SSL';
		} else {
			$days = (int) $ssl_days;
			if ( $days < 0 ) {
				$critical[] = sprintf( 'Certyfikat SSL wygasł %d %s temu', abs( $days ), self::days_word( abs( $days ) ) );
			} elseif ( $days <= self::SSL_CRITICAL_DAYS ) {
				$critical[] = sprintf( 'Certyfikat SSL wygasa za %d %s', $days, self::days_word( $days ) );
			} elseif ( $days <= self::SSL_WARNING_DAYS ) {
				$warning[] = sprintf( 'Certyfikat SSL wygasa za %d %s', $days, self::days_word( $days ) );
			}
		}

		if ( ! empty( $s['core_update'] ) ) {
			$version   = isset( $s['core_update_version'] ) ? (string) $s['core_update_version'] : '';
			$warning[] = '' !== $version
				? sprintf( 'Dostępna aktualizacja WordPressa do wersji %s', $version )
				: 'Dostępna aktualizacja WordPressa';
		}

		$plugins = isset( $s['plugin_updates'] ) && is_array( $s['plugin_updates'] ) ? count( $s['plugin_updates'] ) : 0;
		if ( $plugins >= self::PLUGIN_UPDATES_CRITICAL ) {
			$critical[] = sprintf( 'Wtyczki do aktualizacji: %d', $plugins );
		} elseif ( $plugins > 0 ) {
			$warning[] = sprintf( 'Wtyczki do aktualizacji: %d', $plugins );
		}

		$themes = isset( $s['theme_updates'] ) && is_array( $s['theme_updates'] ) ? count( $s['theme_updates'] ) : 0;
		if ( $themes > 0 ) {
			$warning[] = sprintf( 'Motywy do aktualizacji: %d', $themes );
		}

		if ( ! empty( $s['php_version'] ) ) {
			$php = (string) $s['php_version'];
			if ( version_compare( $php, self::PHP_CRITICAL_BELOW, '<' ) ) {
				$critical[] = sprintf( 'Przestarzała wersja PHP %s — brak wsparcia bezpieczeństwa', $php );
			} elseif ( version_compare( $php, self::PHP_WARNING_BELOW, '<' ) ) {
				$warning[] = sprintf( 'Wersja PHP %s nie jest już wspierana — zalecana %s lub nowsza', $php, self::PHP_WARNING_BELOW );
			}
		}

		if ( ! empty( $s['debug_mode'] ) ) {
			$warning[] = ! empty( $s['debug_display'] )
				? 'Włączony tryb debugowania z wyświetlaniem błędów (WP_DEBUG_DISPLAY)'
				: 'Włączony tryb debugowania (WP_DEBUG)';
		}

		if ( isset( $s['disk_free_mb'] ) && null !== $s['disk_free_mb'] ) {
			$mb = (int) $s['disk_free_mb'];
			if ( $mb < self::DISK_CRITICAL_MB ) {
				$critical[] = sprintf( 'Krytycznie mało miejsca na dysku: %d MB', $mb );
			} elseif ( $mb < self::DISK_WARNING_MB ) {
				$warning[] = sprintf( 'Mało miejsca na dysku: %d MB', $mb );
			}
		}

		if ( isset( $s['last_cron_age'] ) && null !== $s['last_cron_age'] ) {
			$age = (int) $s['last_cron_age'];
			if ( $age > self::CRON_WARNING_SECONDS ) {
				$warning[] = sprintf( 'WP-Cron nie uruchamiał się od %d godz.', (int) floor( $age / 3600 ) );
			}
		}

		if ( array_key_exists( 'blog_public', $s ) && ! $s['blog_public'] ) {
			$warning[] = 'Strona blokuje indeksowanie przez wyszukiwarki';
		}

		if ( $critical ) {
			$health = self::HEALTH_CRITICAL;
		} elseif ( $warning ) {
			$health = self::HEALTH_WARNING;
		} else {
			$health = self::HEALTH_OK;
		}

		return array(
			'health'  => $health,
			'reasons' => array_values( array_merge( $critical, $warning ) ),
		);
	}

	/**
	 * Polska odmiana słowa "dzień".
	 *
	 * @param int $n Liczba dni.
	 * @return string
	 */
	public static function days_word( $n ) {
		return 1 === (int) $n ? 'dzień' : 'dni';
	}

	/**
	 * Liczba pełnych dni do wygaśnięcia certyfikatu (ujemna = po terminie).
	 *
	 * @param int $valid_to Znacznik czasu końca ważności.
	 * @param int $now      Bieżący znacznik czasu.
	 * @return int
	 */
	public static function ssl_days_left( $valid_to, $now ) {
		return (int) floor( ( (int) $valid_to - (int) $now ) / 86400 );
	}

	/**
	 * Rozpoznanie typu urządzenia po User-Agencie (tablety liczone jako mobile).
	 *
	 * @param string $ua User-Agent.
	 * @return string "mobile" lub "desktop".
	 */
	public static function detect_device( $ua ) {
		$ua = (string) $ua;
		if ( preg_match( '/Mobi|Android|iPhone|iPad|iPod|Windows Phone|IEMobile|Opera Mini|BlackBerry|BB10|webOS|Silk|Kindle|Tablet/i', $ua ) ) {
			return 'mobile';
		}
		return 'desktop';
	}

	/**
	 * Czy User-Agent należy do bota / narzędzia automatycznego.
	 *
	 * @param string $ua User-Agent.
	 * @return bool
	 */
	public static function is_bot( $ua ) {
		$ua = trim( (string) $ua );
		if ( '' === $ua || strlen( $ua ) < 10 ) {
			return true;
		}
		return (bool) preg_match(
			'/bot\b|bot\/|crawl|spider|slurp|mediapartners|headless|phantomjs|puppeteer|playwright|selenium|lighthouse|pagespeed|gtmetrix|pingdom|uptime|monitor|curl\/|wget|python-|python\/|java\/|go-http|okhttp|axios|node-fetch|httpclient|libwww|facebookexternalhit|facebookcatalog|whatsapp|telegrambot|preview|scrapy|ahrefs|semrush|mj12|dotbot|petalbot|bytespider|gptbot|claudebot|ccbot|yandex|baiduspider|duckduckbot|applebot|bingpreview/i',
			$ua
		);
	}

	/**
	 * Wyciąga samą domenę z odsyłacza (bez www.), pomija własną domenę i śmieci.
	 *
	 * @param string $referrer Pełny adres odsyłacza.
	 * @param string $own_host Host własnej strony.
	 * @return string Domena lub pusty ciąg.
	 */
	public static function referrer_domain( $referrer, $own_host = '' ) {
		$referrer = trim( (string) $referrer );
		if ( '' === $referrer || strlen( $referrer ) > self::MAX_REFERRER_LENGTH ) {
			return '';
		}
		$parts = parse_url( $referrer );
		if ( ! is_array( $parts ) || empty( $parts['host'] ) || empty( $parts['scheme'] ) ) {
			return '';
		}
		$scheme = strtolower( $parts['scheme'] );
		if ( 'http' !== $scheme && 'https' !== $scheme ) {
			return '';
		}
		$host = self::normalize_host( $parts['host'] );
		if ( '' === $host || strlen( $host ) > self::MAX_DOMAIN_LENGTH || ! preg_match( '/^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/', $host ) ) {
			return '';
		}
		if ( '' !== (string) $own_host && self::normalize_host( $own_host ) === $host ) {
			return '';
		}
		return $host;
	}

	/**
	 * Host małymi literami, bez "www." i kropki na końcu.
	 *
	 * @param string $host Host.
	 * @return string
	 */
	public static function normalize_host( $host ) {
		$host = rtrim( strtolower( trim( (string) $host ) ), '.' );
		if ( 0 === strpos( $host, 'www.' ) ) {
			$host = substr( $host, 4 );
		}
		return $host;
	}

	/**
	 * Anonimowy, dzienny identyfikator odwiedzającego. Adres IP nigdy nie jest zapisywany —
	 * trafia tylko do HMAC razem z UA, datą i tajną solą, więc hash zmienia się codziennie.
	 *
	 * @param string $ip   Adres IP.
	 * @param string $ua   User-Agent.
	 * @param string $day  Data Y-m-d.
	 * @param string $salt Tajna sól strony.
	 * @return string 32 znaki hex.
	 */
	public static function visitor_hash( $ip, $ua, $day, $salt ) {
		return substr( hash_hmac( 'sha256', (string) $ip . '|' . (string) $ua . '|' . (string) $day, (string) $salt ), 0, 32 );
	}

	/**
	 * Anonimowy klucz limitu żądań dla adresu IP (bez UA — zmiana User-Agenta go nie omija).
	 *
	 * @param string $ip   Adres IP.
	 * @param string $day  Data Y-m-d.
	 * @param string $salt Tajna sól strony.
	 * @return string 32 znaki hex.
	 */
	public static function ip_bucket( $ip, $day, $salt ) {
		return substr( hash_hmac( 'sha256', 'rl|' . (string) $ip . '|' . (string) $day, (string) $salt ), 0, 32 );
	}

	/**
	 * Krok limitu żądań w stałym oknie (licznik nie przedłuża okna przy każdym żądaniu).
	 *
	 * @param mixed $state  Zapisany stan array{n:int,t:int} lub cokolwiek (= brak).
	 * @param int   $now    Bieżący znacznik czasu.
	 * @param int   $limit  Maksymalna liczba żądań w oknie.
	 * @param int   $window Długość okna w sekundach.
	 * @return array{0:bool,1:array,2:int} [czy dozwolone, nowy stan, TTL w sekundach].
	 */
	public static function rate_limit_step( $state, $now, $limit, $window ) {
		$now    = (int) $now;
		$window = max( 1, (int) $window );
		if ( ! is_array( $state ) || ! isset( $state['n'], $state['t'] ) || $now - (int) $state['t'] >= $window || (int) $state['t'] > $now ) {
			$state = array(
				'n' => 0,
				't' => $now,
			);
		}
		$state = array(
			'n' => (int) $state['n'],
			't' => (int) $state['t'],
		);
		$ttl   = max( 1, $window - ( $now - $state['t'] ) );
		if ( $state['n'] >= (int) $limit ) {
			return array( false, $state, $ttl );
		}
		$state['n']++;
		return array( true, $state, $ttl );
	}

	/**
	 * Normalizacja statusu zgody z różnych wtyczek cookie.
	 *
	 * @param mixed $status Status (string/bool).
	 * @return string|null accepted_all | rejected | custom lub null gdy nieznany.
	 */
	public static function normalize_consent( $status ) {
		if ( true === $status ) {
			return self::CONSENT_ACCEPTED;
		}
		if ( false === $status ) {
			return self::CONSENT_REJECTED;
		}
		if ( ! is_string( $status ) || strlen( $status ) > 40 ) {
			return null;
		}
		$s = strtolower( trim( $status ) );
		$s = preg_replace( '/[\s\-]+/', '_', $s );

		$accepted = array( 'accepted', 'accepted_all', 'accept', 'accept_all', 'acceptall', 'allow', 'allow_all', 'allowed', 'all', 'granted', 'yes', 'true', '1', 'agree', 'opt_in', 'optin' );
		$rejected = array( 'rejected', 'rejected_all', 'reject', 'reject_all', 'rejectall', 'deny', 'denied', 'deny_all', 'decline', 'declined', 'no', 'false', '0', 'necessary', 'necessary_only', 'essential', 'essential_only', 'opt_out', 'optout' );
		$custom   = array( 'custom', 'partial', 'partially', 'mixed', 'preferences', 'selected', 'selection', 'some', 'customized' );

		if ( in_array( $s, $accepted, true ) ) {
			return self::CONSENT_ACCEPTED;
		}
		if ( in_array( $s, $rejected, true ) ) {
			return self::CONSENT_REJECTED;
		}
		if ( in_array( $s, $custom, true ) ) {
			return self::CONSENT_CUSTOM;
		}
		return null;
	}

	/**
	 * Oczyszcza ścieżkę strony: bez query stringa i fragmentu, max 255 znaków.
	 *
	 * @param mixed $path Ścieżka z przeglądarki.
	 * @return string|null Null, gdy dane są nieprawidłowe.
	 */
	public static function sanitize_path( $path ) {
		if ( ! is_string( $path ) || '' === $path || strlen( $path ) > self::MAX_RAW_PATH_LENGTH ) {
			return null;
		}
		$path = preg_replace( '/[?#].*$/s', '', $path );
		$path = preg_replace( '/[\x00-\x1F\x7F\s<>"\'`]/', '', $path );
		if ( '' === $path || '/' !== $path[0] || 0 === strpos( $path, '//' ) ) {
			return null;
		}
		if ( strlen( $path ) > self::MAX_PATH_LENGTH ) {
			$path = substr( $path, 0, self::MAX_PATH_LENGTH );
		}
		return $path;
	}

	/**
	 * Liczba dni analityki w dozwolonym zakresie 1–365 (domyślnie 30).
	 *
	 * @param mixed $days Wartość z zapytania.
	 * @return int
	 */
	public static function clamp_days( $days ) {
		if ( ! is_numeric( $days ) ) {
			return 30;
		}
		return max( 1, min( 365, (int) $days ) );
	}

	/**
	 * Lista dat Y-m-d od $from do $to włącznie.
	 *
	 * @param string $from Data początkowa.
	 * @param string $to   Data końcowa.
	 * @return array<int,string>
	 */
	public static function date_range( $from, $to ) {
		$tz    = new DateTimeZone( 'UTC' );
		$start = DateTimeImmutable::createFromFormat( '!Y-m-d', (string) $from, $tz );
		$end   = DateTimeImmutable::createFromFormat( '!Y-m-d', (string) $to, $tz );
		if ( ! $start || ! $end || $start > $end ) {
			return array();
		}
		$out = array();
		for ( $d = $start; $d <= $end && count( $out ) < 3660; $d = $d->modify( '+1 day' ) ) {
			$out[] = $d->format( 'Y-m-d' );
		}
		return $out;
	}

	/**
	 * Uzupełnia dzienną serię zerami dla dni bez danych.
	 *
	 * @param array  $rows   Wiersze z kluczem "day" i polami liczbowymi.
	 * @param string $from   Data początkowa.
	 * @param string $to     Data końcowa.
	 * @param array  $fields Nazwy pól liczbowych.
	 * @return array<int,array>
	 */
	public static function fill_daily_series( array $rows, $from, $to, array $fields ) {
		$by_day = array();
		foreach ( $rows as $row ) {
			$row = (array) $row;
			if ( isset( $row['day'] ) ) {
				$by_day[ (string) $row['day'] ] = $row;
			}
		}
		$out = array();
		foreach ( self::date_range( $from, $to ) as $day ) {
			$item = array( 'date' => $day );
			foreach ( $fields as $field ) {
				$item[ $field ] = isset( $by_day[ $day ][ $field ] ) ? (int) $by_day[ $day ][ $field ] : 0;
			}
			$out[] = $item;
		}
		return $out;
	}

	/**
	 * Procent akceptacji wszystkich cookies (accepted_all / wszystkie decyzje).
	 *
	 * @param int $accepted Liczba pełnych akceptacji.
	 * @param int $total    Liczba wszystkich decyzji.
	 * @return float|null
	 */
	public static function acceptance_rate( $accepted, $total ) {
		$total = (int) $total;
		if ( $total <= 0 ) {
			return null;
		}
		return round( (int) $accepted / $total * 100, 1 );
	}

	/**
	 * Podsumowanie zgód: seria dzienna, sumy i procent akceptacji.
	 *
	 * @param array  $rows Wiersze {day, status, count}.
	 * @param string $from Data początkowa.
	 * @param string $to   Data końcowa.
	 * @return array
	 */
	public static function consent_summary( array $rows, $from, $to ) {
		$statuses = array( self::CONSENT_ACCEPTED, self::CONSENT_REJECTED, self::CONSENT_CUSTOM );
		$pivot    = array();
		foreach ( $rows as $row ) {
			$row    = (array) $row;
			$status = isset( $row['status'] ) ? (string) $row['status'] : '';
			if ( ! isset( $row['day'] ) || ! in_array( $status, $statuses, true ) ) {
				continue;
			}
			$day = (string) $row['day'];
			if ( ! isset( $pivot[ $day ] ) ) {
				$pivot[ $day ] = array( 'day' => $day );
			}
			$pivot[ $day ][ $status ] = ( isset( $pivot[ $day ][ $status ] ) ? $pivot[ $day ][ $status ] : 0 ) + (int) $row['count'];
		}
		$daily  = self::fill_daily_series( array_values( $pivot ), $from, $to, $statuses );
		$totals = array_fill_keys( $statuses, 0 );
		foreach ( $daily as $item ) {
			foreach ( $statuses as $status ) {
				$totals[ $status ] += $item[ $status ];
			}
		}
		$totals['total'] = array_sum( array_intersect_key( $totals, array_flip( $statuses ) ) );
		return array(
			'daily'           => $daily,
			'totals'          => $totals,
			'acceptance_rate' => self::acceptance_rate( $totals[ self::CONSENT_ACCEPTED ], $totals['total'] ),
		);
	}
}
