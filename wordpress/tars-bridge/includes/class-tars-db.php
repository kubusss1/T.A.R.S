<?php
/**
 * Tabele, opcje i zadania cron TARS Bridge.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Warstwa danych: tabele {prefix}tars_hits i {prefix}tars_consent.
 */
final class TARS_Bridge_DB {

	const DB_VERSION       = '1';
	const RETENTION_DAYS   = 180;
	const OPT_KEY          = 'tars_bridge_api_key';
	const OPT_SALT         = 'tars_bridge_salt';
	const OPT_DB_VERSION   = 'tars_bridge_db_version';
	const OPT_LAST_CRON    = 'tars_bridge_last_cron';
	const OPT_SETTINGS     = 'tars_bridge_settings';
	const CRON_PRUNE       = 'tars_bridge_prune';
	const CRON_HEARTBEAT   = 'tars_bridge_heartbeat';
	const TRANSIENT_SSL    = 'tars_bridge_ssl';

	/**
	 * Nazwa tabeli odsłon.
	 *
	 * @return string
	 */
	public static function hits_table() {
		global $wpdb;
		return $wpdb->prefix . 'tars_hits';
	}

	/**
	 * Nazwa tabeli zgód.
	 *
	 * @return string
	 */
	public static function consent_table() {
		global $wpdb;
		return $wpdb->prefix . 'tars_consent';
	}

	/**
	 * Aktywacja: tabele, klucz API, sól, zadania cron.
	 */
	public static function activate() {
		self::create_tables();
		self::ensure_secrets();
		if ( false === get_option( self::OPT_SETTINGS ) ) {
			add_option( self::OPT_SETTINGS, self::default_settings(), '', 'yes' );
		}
		self::register_cron();
	}

	/**
	 * Dezaktywacja: usuwa zadania cron (dane zostają do odinstalowania).
	 */
	public static function deactivate() {
		wp_clear_scheduled_hook( self::CRON_PRUNE );
		wp_clear_scheduled_hook( self::CRON_HEARTBEAT );
	}

	/**
	 * Aktualizacja schematu po podmianie plików wtyczki.
	 */
	public static function maybe_upgrade() {
		if ( get_option( self::OPT_DB_VERSION ) !== self::DB_VERSION ) {
			self::create_tables();
		}
		self::ensure_secrets();
	}

	/**
	 * Domyślne ustawienia.
	 *
	 * @return array
	 */
	public static function default_settings() {
		return array(
			'tracking'    => 1,
			'respect_dnt' => 1,
		);
	}

	/**
	 * Aktualne ustawienia z domyślnymi wartościami.
	 *
	 * @return array
	 */
	public static function settings() {
		$saved = get_option( self::OPT_SETTINGS, array() );
		return wp_parse_args( is_array( $saved ) ? $saved : array(), self::default_settings() );
	}

	/**
	 * Generuje klucz API i sól, jeśli ich brak.
	 */
	public static function ensure_secrets() {
		if ( ! get_option( self::OPT_KEY ) ) {
			update_option( self::OPT_KEY, self::generate_key(), false );
		}
		if ( ! get_option( self::OPT_SALT ) ) {
			update_option( self::OPT_SALT, wp_generate_password( 64, true, true ), false );
		}
	}

	/**
	 * Nowy losowy klucz API (bez znaków specjalnych — łatwy do wklejenia w JSON).
	 *
	 * @return string
	 */
	public static function generate_key() {
		return wp_generate_password( 40, false, false );
	}

	/**
	 * Klucz API.
	 *
	 * @return string
	 */
	public static function api_key() {
		return (string) get_option( self::OPT_KEY, '' );
	}

	/**
	 * Sól do hashowania odwiedzających.
	 *
	 * @return string
	 */
	public static function salt() {
		$salt = (string) get_option( self::OPT_SALT, '' );
		return '' !== $salt ? $salt : wp_salt( 'auth' );
	}

	/**
	 * Tworzy / aktualizuje tabele przez dbDelta.
	 */
	public static function create_tables() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';

		$charset = $wpdb->get_charset_collate();
		$hits    = self::hits_table();
		$consent = self::consent_table();

		$sql_hits = "CREATE TABLE {$hits} (
  id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  day date NOT NULL,
  created_at datetime NOT NULL,
  visitor char(32) NOT NULL,
  path varchar(255) NOT NULL DEFAULT '',
  referrer varchar(191) NOT NULL DEFAULT '',
  device varchar(10) NOT NULL DEFAULT 'desktop',
  PRIMARY KEY  (id),
  KEY day (day),
  KEY day_visitor (day,visitor)
) {$charset};";

		$sql_consent = "CREATE TABLE {$consent} (
  id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  day date NOT NULL,
  created_at datetime NOT NULL,
  visitor char(32) NOT NULL,
  status varchar(12) NOT NULL,
  source varchar(20) NOT NULL DEFAULT '',
  PRIMARY KEY  (id),
  UNIQUE KEY day_visitor (day,visitor),
  KEY day (day)
) {$charset};";

		dbDelta( $sql_hits );
		dbDelta( $sql_consent );
		update_option( self::OPT_DB_VERSION, self::DB_VERSION );
	}

	/**
	 * Rejestruje zadania cron i ich obsługę.
	 */
	public static function register_cron() {
		add_action( self::CRON_PRUNE, array( __CLASS__, 'prune' ) );
		add_action( self::CRON_HEARTBEAT, array( __CLASS__, 'heartbeat' ) );
		if ( ! wp_next_scheduled( self::CRON_PRUNE ) ) {
			wp_schedule_event( time() + HOUR_IN_SECONDS, 'daily', self::CRON_PRUNE );
		}
		if ( ! wp_next_scheduled( self::CRON_HEARTBEAT ) ) {
			wp_schedule_event( time(), 'hourly', self::CRON_HEARTBEAT );
		}
	}

	/**
	 * Zapisuje czas ostatniego uruchomienia WP-Cron.
	 */
	public static function heartbeat() {
		update_option( self::OPT_LAST_CRON, time(), false );
	}

	/**
	 * Usuwa dane starsze niż 180 dni.
	 */
	public static function prune() {
		global $wpdb;
		self::heartbeat();
		$cutoff  = gmdate( 'Y-m-d', current_time( 'timestamp' ) - self::RETENTION_DAYS * DAY_IN_SECONDS ); // phpcs:ignore WordPress.DateTime.CurrentTimeTimestamp.Requested
		$hits    = self::hits_table();
		$consent = self::consent_table();
		// phpcs:disable WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- nazwy tabel są stałe.
		$wpdb->query( $wpdb->prepare( "DELETE FROM {$hits} WHERE day < %s", $cutoff ) );
		$wpdb->query( $wpdb->prepare( "DELETE FROM {$consent} WHERE day < %s", $cutoff ) );
		// phpcs:enable
	}

	/**
	 * Zapisuje odsłonę.
	 *
	 * @param array $hit {day, visitor, path, referrer, device}.
	 * @return bool
	 */
	public static function insert_hit( array $hit ) {
		global $wpdb;
		return false !== $wpdb->insert(
			self::hits_table(),
			array(
				'day'        => $hit['day'],
				'created_at' => current_time( 'mysql' ),
				'visitor'    => $hit['visitor'],
				'path'       => $hit['path'],
				'referrer'   => $hit['referrer'],
				'device'     => $hit['device'],
			),
			array( '%s', '%s', '%s', '%s', '%s', '%s' )
		);
	}

	/**
	 * Zapisuje decyzję zgody — jedna na odwiedzającego dziennie (ostatnia wygrywa).
	 *
	 * @param string $day     Data Y-m-d.
	 * @param string $visitor Hash odwiedzającego.
	 * @param string $status  accepted_all|rejected|custom.
	 * @param string $source  Źródło (wtyczka cookie).
	 * @return bool
	 */
	public static function upsert_consent( $day, $visitor, $status, $source ) {
		global $wpdb;
		$table = self::consent_table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- nazwa tabeli jest stała.
		$sql = $wpdb->prepare( "INSERT INTO {$table} (day, created_at, visitor, status, source) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE status = VALUES(status), source = VALUES(source)", $day, current_time( 'mysql' ), $visitor, $status, $source );
		return false !== $wpdb->query( $sql ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	}

	/**
	 * Dane analityczne za okres.
	 *
	 * @param int $days Liczba dni (1–365).
	 * @return array
	 */
	public static function analytics( $days ) {
		global $wpdb;
		$days    = TARS_Logic::clamp_days( $days );
		$now     = current_time( 'timestamp' ); // phpcs:ignore WordPress.DateTime.CurrentTimeTimestamp.Requested
		$to      = gmdate( 'Y-m-d', $now );
		$from    = gmdate( 'Y-m-d', $now - ( $days - 1 ) * DAY_IN_SECONDS );
		$hits    = self::hits_table();
		$consent = self::consent_table();

		// phpcs:disable WordPress.DB.PreparedSQL.InterpolatedNotPrepared, WordPress.DB.DirectDatabaseQuery -- nazwy tabel są stałe, dane dynamiczne.
		$daily_rows = $wpdb->get_results( $wpdb->prepare( "SELECT day, COUNT(*) AS views, COUNT(DISTINCT visitor) AS visitors FROM {$hits} WHERE day BETWEEN %s AND %s GROUP BY day ORDER BY day", $from, $to ), ARRAY_A );
		$pages      = $wpdb->get_results( $wpdb->prepare( "SELECT path, COUNT(*) AS views FROM {$hits} WHERE day BETWEEN %s AND %s GROUP BY path ORDER BY views DESC LIMIT 10", $from, $to ), ARRAY_A );
		$refs       = $wpdb->get_results( $wpdb->prepare( "SELECT referrer, COUNT(*) AS visits FROM {$hits} WHERE day BETWEEN %s AND %s AND referrer <> '' GROUP BY referrer ORDER BY visits DESC LIMIT 10", $from, $to ), ARRAY_A );
		$devices    = $wpdb->get_results( $wpdb->prepare( "SELECT device, COUNT(DISTINCT day, visitor) AS visitors FROM {$hits} WHERE day BETWEEN %s AND %s GROUP BY device", $from, $to ), ARRAY_A );
		$consents   = $wpdb->get_results( $wpdb->prepare( "SELECT day, status, COUNT(*) AS count FROM {$consent} WHERE day BETWEEN %s AND %s GROUP BY day, status", $from, $to ), ARRAY_A );
		// phpcs:enable

		$daily  = TARS_Logic::fill_daily_series( (array) $daily_rows, $from, $to, array( 'views', 'visitors' ) );
		$totals = array(
			'views'    => 0,
			'visitors' => 0,
		);
		foreach ( $daily as $item ) {
			$totals['views']    += $item['views'];
			$totals['visitors'] += $item['visitors'];
		}

		$device_counts = array(
			'mobile'  => 0,
			'desktop' => 0,
		);
		foreach ( (array) $devices as $row ) {
			if ( isset( $device_counts[ $row['device'] ] ) ) {
				$device_counts[ $row['device'] ] = (int) $row['visitors'];
			}
		}

		return array(
			'days'      => $days,
			'from'      => $from,
			'to'        => $to,
			'daily'     => $daily,
			'totals'    => $totals,
			'top_pages' => array_map(
				static function ( $r ) {
					return array(
						'path'  => (string) $r['path'],
						'views' => (int) $r['views'],
					);
				},
				(array) $pages
			),
			'referrers' => array_map(
				static function ( $r ) {
					return array(
						'domain' => (string) $r['referrer'],
						'visits' => (int) $r['visits'],
					);
				},
				(array) $refs
			),
			'devices'   => $device_counts,
			'consent'   => TARS_Logic::consent_summary( (array) $consents, $from, $to ),
		);
	}
}
