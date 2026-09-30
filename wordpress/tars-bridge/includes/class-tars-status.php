<?php
/**
 * Zbieranie statusu strony dla panelu TARS.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Status: wersje, aktualizacje, SSL, dysk, cron, kondycja.
 */
final class TARS_Bridge_Status {

	/**
	 * Pełny raport statusu.
	 *
	 * @return array
	 */
	public static function collect() {
		global $wp_version;

		$home   = home_url( '/' );
		$scheme = wp_parse_url( $home, PHP_URL_SCHEME );
		$https  = 'https' === $scheme;

		$core    = self::core_update();
		$plugins = self::plugin_updates();
		$themes  = self::theme_updates();
		$ssl     = $https ? self::ssl_info() : array(
			'days'    => null,
			'expires' => null,
		);

		$last_cron     = (int) get_option( TARS_Bridge_DB::OPT_LAST_CRON, 0 );
		$last_cron_age = $last_cron > 0 ? max( 0, time() - $last_cron ) : null;
		$disk_free_mb  = self::disk_free_mb();

		if ( ! function_exists( 'get_plugins' ) ) {
			require_once ABSPATH . 'wp-admin/includes/plugin.php';
		}
		$active_plugins = (array) get_option( 'active_plugins', array() );
		if ( is_multisite() ) {
			$active_plugins = array_merge( $active_plugins, array_keys( (array) get_site_option( 'active_sitewide_plugins', array() ) ) );
		}

		$data = array(
			'site'                => array(
				'name' => wp_specialchars_decode( get_bloginfo( 'name' ), ENT_QUOTES ),
				'url'  => $home,
			),
			'plugin_version'      => TARS_BRIDGE_VERSION,
			'wp_version'          => (string) $wp_version,
			'php_version'         => PHP_VERSION,
			'https'               => $https,
			'core_update'         => array(
				'available' => null !== $core,
				'version'   => $core,
			),
			'plugin_updates'      => $plugins,
			'theme_updates'       => $themes,
			'updates_count'       => ( null !== $core ? 1 : 0 ) + count( $plugins ) + count( $themes ),
			'active_plugins'      => count( array_unique( $active_plugins ) ),
			'ssl_days'            => $ssl['days'],
			'ssl_expires'         => $ssl['expires'],
			'debug_mode'          => defined( 'WP_DEBUG' ) && WP_DEBUG,
			'debug_display'       => defined( 'WP_DEBUG' ) && WP_DEBUG && ( ! defined( 'WP_DEBUG_DISPLAY' ) || WP_DEBUG_DISPLAY ),
			'disk_free_mb'        => $disk_free_mb,
			'last_cron_run'       => $last_cron > 0 ? gmdate( 'c', $last_cron ) : null,
			'wp_cron_disabled'    => defined( 'DISABLE_WP_CRON' ) && DISABLE_WP_CRON,
			'blog_public'         => (bool) get_option( 'blog_public', 1 ),
			'server_time'         => wp_date( 'c' ),
			'timezone'            => wp_timezone_string(),
			'updates_checked_at'  => self::updates_checked_at(),
		);

		$health = TARS_Logic::evaluate_health(
			array(
				'https'               => $https,
				'ssl_days'            => $ssl['days'],
				'core_update'         => null !== $core,
				'core_update_version' => (string) $core,
				'plugin_updates'      => $plugins,
				'theme_updates'       => $themes,
				'php_version'         => PHP_VERSION,
				'debug_mode'          => $data['debug_mode'],
				'debug_display'       => $data['debug_display'],
				'disk_free_mb'        => $disk_free_mb,
				'last_cron_age'       => $last_cron_age,
				'blog_public'         => $data['blog_public'],
			)
		);

		$data['health']  = $health['health'];
		$data['reasons'] = $health['reasons'];
		return $data;
	}

	/**
	 * Wersja dostępnej aktualizacji WordPressa lub null.
	 *
	 * @return string|null
	 */
	private static function core_update() {
		$t = get_site_transient( 'update_core' );
		if ( ! is_object( $t ) || empty( $t->updates ) || ! is_array( $t->updates ) ) {
			return null;
		}
		foreach ( $t->updates as $u ) {
			if ( is_object( $u ) && isset( $u->response ) && 'upgrade' === $u->response && ! empty( $u->current ) ) {
				return (string) $u->current;
			}
		}
		return null;
	}

	/**
	 * Lista wtyczek z dostępnymi aktualizacjami.
	 *
	 * @return array<int,array{name:string,current:string,new:string}>
	 */
	private static function plugin_updates() {
		$t = get_site_transient( 'update_plugins' );
		if ( ! is_object( $t ) || empty( $t->response ) || ! is_array( $t->response ) ) {
			return array();
		}
		if ( ! function_exists( 'get_plugins' ) ) {
			require_once ABSPATH . 'wp-admin/includes/plugin.php';
		}
		$all = get_plugins();
		$out = array();
		foreach ( $t->response as $file => $info ) {
			if ( ! isset( $all[ $file ] ) ) {
				continue;
			}
			$new = is_object( $info ) && isset( $info->new_version ) ? (string) $info->new_version : '';
			$out[] = array(
				'name'    => wp_strip_all_tags( (string) $all[ $file ]['Name'] ),
				'current' => (string) $all[ $file ]['Version'],
				'new'     => $new,
			);
		}
		return $out;
	}

	/**
	 * Lista motywów z dostępnymi aktualizacjami.
	 *
	 * @return array<int,array{name:string,current:string,new:string}>
	 */
	private static function theme_updates() {
		$t = get_site_transient( 'update_themes' );
		if ( ! is_object( $t ) || empty( $t->response ) || ! is_array( $t->response ) ) {
			return array();
		}
		$out = array();
		foreach ( $t->response as $slug => $info ) {
			$theme = wp_get_theme( $slug );
			if ( ! $theme->exists() ) {
				continue;
			}
			$info  = (array) $info;
			$out[] = array(
				'name'    => wp_strip_all_tags( (string) $theme->get( 'Name' ) ),
				'current' => (string) $theme->get( 'Version' ),
				'new'     => isset( $info['new_version'] ) ? (string) $info['new_version'] : '',
			);
		}
		return $out;
	}

	/**
	 * Czas ostatniego sprawdzenia aktualizacji wtyczek (ISO 8601) lub null.
	 *
	 * @return string|null
	 */
	private static function updates_checked_at() {
		$t = get_site_transient( 'update_plugins' );
		return is_object( $t ) && ! empty( $t->last_checked ) ? gmdate( 'c', (int) $t->last_checked ) : null;
	}

	/**
	 * Wolne miejsce na dysku w MB (null, gdy funkcja niedostępna).
	 *
	 * @return int|null
	 */
	private static function disk_free_mb() {
		if ( ! function_exists( 'disk_free_space' ) ) {
			return null;
		}
		$disabled = array_map( 'trim', explode( ',', (string) ini_get( 'disable_functions' ) ) );
		if ( in_array( 'disk_free_space', $disabled, true ) ) {
			return null;
		}
		$free = @disk_free_space( ABSPATH ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged -- open_basedir może blokować.
		return false === $free ? null : (int) floor( $free / 1048576 );
	}

	/**
	 * Dni do wygaśnięcia certyfikatu SSL (cache 12 h, błąd cache 1 h).
	 *
	 * @return array{days:int|null,expires:string|null}
	 */
	public static function ssl_info() {
		$cached = get_transient( TARS_Bridge_DB::TRANSIENT_SSL );
		if ( is_array( $cached ) && array_key_exists( 'valid_to', $cached ) ) {
			$valid_to = $cached['valid_to'];
		} else {
			$valid_to = self::fetch_ssl_valid_to();
			set_transient(
				TARS_Bridge_DB::TRANSIENT_SSL,
				array( 'valid_to' => $valid_to ),
				null === $valid_to ? HOUR_IN_SECONDS : 12 * HOUR_IN_SECONDS
			);
		}
		if ( null === $valid_to ) {
			return array(
				'days'    => null,
				'expires' => null,
			);
		}
		return array(
			'days'    => TARS_Logic::ssl_days_left( (int) $valid_to, time() ),
			'expires' => gmdate( 'c', (int) $valid_to ),
		);
	}

	/**
	 * Łączy się z własnym hostem na porcie 443 i odczytuje datę końca ważności certyfikatu.
	 *
	 * @return int|null
	 */
	private static function fetch_ssl_valid_to() {
		if ( ! function_exists( 'stream_socket_client' ) || ! function_exists( 'openssl_x509_parse' ) ) {
			return null;
		}
		$host = wp_parse_url( home_url(), PHP_URL_HOST );
		$port = wp_parse_url( home_url(), PHP_URL_PORT );
		if ( ! $host ) {
			return null;
		}
		$context = stream_context_create(
			array(
				'ssl' => array(
					'capture_peer_cert' => true,
					'verify_peer'       => false,
					'verify_peer_name'  => false,
					'SNI_enabled'       => true,
					'peer_name'         => $host,
				),
			)
		);
		$errno  = 0;
		$errstr = '';
		$client = @stream_socket_client( // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged
			'ssl://' . $host . ':' . ( $port ? (int) $port : 443 ),
			$errno,
			$errstr,
			5,
			STREAM_CLIENT_CONNECT,
			$context
		);
		if ( ! $client ) {
			return null;
		}
		$params = stream_context_get_params( $client );
		fclose( $client ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_fclose
		if ( empty( $params['options']['ssl']['peer_certificate'] ) ) {
			return null;
		}
		$cert = openssl_x509_parse( $params['options']['ssl']['peer_certificate'] );
		if ( ! is_array( $cert ) || empty( $cert['validTo_time_t'] ) ) {
			return null;
		}
		return (int) $cert['validTo_time_t'];
	}
}
