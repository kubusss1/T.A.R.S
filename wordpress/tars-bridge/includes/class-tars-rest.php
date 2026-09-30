<?php
/**
 * REST API: namespace tars/v1.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Endpointy: GET /status, GET /analytics (klucz X-TARS-Key), POST /hit, POST /consent (publiczne).
 */
final class TARS_Bridge_REST {

	const NAMESPACE_V1 = 'tars/v1';

	/** Limit odsłon na odwiedzającego w oknie czasowym. */
	const HIT_LIMIT = 60;
	/** Limit zgłoszeń zgody na odwiedzającego w oknie czasowym. */
	const CONSENT_LIMIT = 10;
	/** Okno limitu w sekundach. */
	const RATE_WINDOW = 600;
	/** Limit żądań z jednego adresu IP w oknie (niezależnie od User-Agenta; NAT biura/sieci komórkowej). */
	const IP_LIMIT = 600;

	/**
	 * Podpina rejestrację tras.
	 */
	public static function register() {
		add_action( 'rest_api_init', array( __CLASS__, 'routes' ) );
	}

	/**
	 * Rejestruje trasy.
	 */
	public static function routes() {
		register_rest_route(
			self::NAMESPACE_V1,
			'/status',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( __CLASS__, 'get_status' ),
				'permission_callback' => array( __CLASS__, 'check_key' ),
			)
		);

		register_rest_route(
			self::NAMESPACE_V1,
			'/analytics',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => array( __CLASS__, 'get_analytics' ),
				'permission_callback' => array( __CLASS__, 'check_key' ),
				'args'                => array(
					'days' => array(
						'type'              => 'integer',
						'default'           => 30,
						'validate_callback' => static function ( $value ) {
							return is_numeric( $value );
						},
						'sanitize_callback' => array( 'TARS_Logic', 'clamp_days' ),
					),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE_V1,
			'/hit',
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => array( __CLASS__, 'post_hit' ),
				'permission_callback' => '__return_true', // Publiczny: anonimowi odwiedzający, bez nonce (cache stron).
				'args'                => array(
					'path'     => array(
						'type'              => 'string',
						'required'          => true,
						'validate_callback' => static function ( $value ) {
							return null !== TARS_Logic::sanitize_path( $value );
						},
					),
					'referrer' => array(
						'type'              => 'string',
						'default'           => '',
						'validate_callback' => static function ( $value ) {
							return is_string( $value ) && strlen( $value ) <= TARS_Logic::MAX_REFERRER_LENGTH;
						},
					),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE_V1,
			'/consent',
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => array( __CLASS__, 'post_consent' ),
				'permission_callback' => '__return_true', // Publiczny: anonimowi odwiedzający, bez nonce (cache stron).
				'args'                => array(
					'status' => array(
						'type'              => 'string',
						'required'          => true,
						'validate_callback' => static function ( $value ) {
							return null !== TARS_Logic::normalize_consent( $value );
						},
					),
					'source' => array(
						'type'              => 'string',
						'default'           => '',
						'validate_callback' => static function ( $value ) {
							return is_string( $value ) && strlen( $value ) <= 40;
						},
					),
				),
			)
		);
	}

	/**
	 * Weryfikacja nagłówka X-TARS-Key (porównanie odporne na timing).
	 *
	 * @param WP_REST_Request $request Żądanie.
	 * @return true|WP_Error
	 */
	public static function check_key( $request ) {
		$expected = TARS_Bridge_DB::api_key();
		$given    = (string) $request->get_header( 'x_tars_key' );
		if ( '' === $expected || '' === $given || ! hash_equals( $expected, $given ) ) {
			return new WP_Error(
				'tars_unauthorized',
				__( 'Nieprawidłowy lub brakujący klucz API (nagłówek X-TARS-Key).', 'tars-bridge' ),
				array( 'status' => 401 )
			);
		}
		return true;
	}

	/**
	 * GET /status.
	 *
	 * @return WP_REST_Response
	 */
	public static function get_status() {
		return self::no_cache( rest_ensure_response( TARS_Bridge_Status::collect() ) );
	}

	/**
	 * GET /analytics?days=30.
	 *
	 * @param WP_REST_Request $request Żądanie.
	 * @return WP_REST_Response
	 */
	public static function get_analytics( $request ) {
		$days = TARS_Logic::clamp_days( $request->get_param( 'days' ) );
		return self::no_cache( rest_ensure_response( TARS_Bridge_DB::analytics( $days ) ) );
	}

	/**
	 * POST /hit — zapis odsłony (bez cookies, bez IP).
	 *
	 * @param WP_REST_Request $request Żądanie.
	 * @return WP_REST_Response|WP_Error
	 */
	public static function post_hit( $request ) {
		$settings = TARS_Bridge_DB::settings();
		if ( empty( $settings['tracking'] ) ) {
			return self::accepted( 'disabled' );
		}
		$origin_error = self::check_origin( $request );
		if ( $origin_error ) {
			return $origin_error;
		}

		$ua = self::user_agent();
		if ( TARS_Logic::is_bot( $ua ) ) {
			return self::accepted( 'bot' );
		}

		$path = TARS_Logic::sanitize_path( $request->get_param( 'path' ) );
		if ( null === $path ) {
			return new WP_Error( 'tars_invalid_path', __( 'Nieprawidłowa ścieżka strony.', 'tars-bridge' ), array( 'status' => 400 ) );
		}

		$day     = current_time( 'Y-m-d' );
		$ip      = self::client_ip();
		$visitor = TARS_Logic::visitor_hash( $ip, $ua, $day, TARS_Bridge_DB::salt() );
		if ( ! self::rate_limit( 'ip', TARS_Logic::ip_bucket( $ip, $day, TARS_Bridge_DB::salt() ), self::IP_LIMIT ) || ! self::rate_limit( 'hit', $visitor, self::HIT_LIMIT ) ) {
			return new WP_Error( 'tars_rate_limited', __( 'Zbyt wiele żądań.', 'tars-bridge' ), array( 'status' => 429 ) );
		}

		$own_host = (string) wp_parse_url( home_url(), PHP_URL_HOST );
		TARS_Bridge_DB::insert_hit(
			array(
				'day'      => $day,
				'visitor'  => $visitor,
				'path'     => $path,
				'referrer' => TARS_Logic::referrer_domain( (string) $request->get_param( 'referrer' ), $own_host ),
				'device'   => TARS_Logic::detect_device( $ua ),
			)
		);
		return self::accepted( 'ok' );
	}

	/**
	 * POST /consent — zapis decyzji z banera cookie.
	 *
	 * @param WP_REST_Request $request Żądanie.
	 * @return WP_REST_Response|WP_Error
	 */
	public static function post_consent( $request ) {
		$settings = TARS_Bridge_DB::settings();
		if ( empty( $settings['tracking'] ) ) {
			return self::accepted( 'disabled' );
		}
		$origin_error = self::check_origin( $request );
		if ( $origin_error ) {
			return $origin_error;
		}
		$ua = self::user_agent();
		if ( TARS_Logic::is_bot( $ua ) ) {
			return self::accepted( 'bot' );
		}
		$status = TARS_Logic::normalize_consent( $request->get_param( 'status' ) );
		if ( null === $status ) {
			return new WP_Error( 'tars_invalid_status', __( 'Nieznany status zgody.', 'tars-bridge' ), array( 'status' => 400 ) );
		}
		$day     = current_time( 'Y-m-d' );
		$ip      = self::client_ip();
		$visitor = TARS_Logic::visitor_hash( $ip, $ua, $day, TARS_Bridge_DB::salt() );
		if ( ! self::rate_limit( 'ip', TARS_Logic::ip_bucket( $ip, $day, TARS_Bridge_DB::salt() ), self::IP_LIMIT ) || ! self::rate_limit( 'consent', $visitor, self::CONSENT_LIMIT ) ) {
			return new WP_Error( 'tars_rate_limited', __( 'Zbyt wiele żądań.', 'tars-bridge' ), array( 'status' => 429 ) );
		}
		$source = substr( sanitize_key( (string) $request->get_param( 'source' ) ), 0, 20 );
		TARS_Bridge_DB::upsert_consent( $day, $visitor, $status, $source );
		return self::accepted( 'ok' );
	}

	/**
	 * Odrzuca żądania z obcego Origin (lekka ochrona przed spamem statystyk).
	 *
	 * @param WP_REST_Request $request Żądanie.
	 * @return WP_Error|null
	 */
	private static function check_origin( $request ) {
		$origin = (string) $request->get_header( 'origin' );
		if ( '' === $origin || 'null' === $origin ) {
			return null;
		}
		$origin_host = TARS_Logic::normalize_host( (string) wp_parse_url( $origin, PHP_URL_HOST ) );
		$allowed     = array(
			TARS_Logic::normalize_host( (string) wp_parse_url( home_url(), PHP_URL_HOST ) ),
			TARS_Logic::normalize_host( (string) wp_parse_url( site_url(), PHP_URL_HOST ) ),
		);
		if ( in_array( $origin_host, $allowed, true ) ) {
			return null;
		}
		return new WP_Error( 'tars_forbidden_origin', __( 'Niedozwolone źródło żądania.', 'tars-bridge' ), array( 'status' => 403 ) );
	}

	/**
	 * Limit żądań na odwiedzającego (transient).
	 *
	 * @param string $bucket  Rodzaj żądania.
	 * @param string $visitor Hash odwiedzającego.
	 * @param int    $limit   Maksymalna liczba w oknie.
	 * @return bool True, gdy żądanie mieści się w limicie.
	 */
	private static function rate_limit( $bucket, $visitor, $limit ) {
		$key  = 'tars_rl_' . $bucket[0] . '_' . substr( $visitor, 0, 24 );
		$step = TARS_Logic::rate_limit_step( get_transient( $key ), time(), $limit, self::RATE_WINDOW );
		if ( ! $step[0] ) {
			return false;
		}
		set_transient( $key, $step[1], $step[2] );
		return true;
	}

	/**
	 * User-Agent żądania (przycięty).
	 *
	 * @return string
	 */
	private static function user_agent() {
		$ua = isset( $_SERVER['HTTP_USER_AGENT'] ) ? sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ) : ''; // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized
		return substr( $ua, 0, 512 );
	}

	/**
	 * Adres IP klienta — używany wyłącznie do hasha, nigdy nie zapisywany.
	 * Za proxy (np. Cloudflare) można go podmienić filtrem `tars_bridge_client_ip`.
	 *
	 * @return string
	 */
	private static function client_ip() {
		$ip = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : ''; // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized
		return (string) apply_filters( 'tars_bridge_client_ip', $ip );
	}

	/**
	 * Krótka odpowiedź 202 dla beaconów.
	 *
	 * @param string $result Wynik.
	 * @return WP_REST_Response
	 */
	private static function accepted( $result ) {
		return self::no_cache( new WP_REST_Response( array( 'result' => $result ), 202 ) );
	}

	/**
	 * Nagłówki wyłączające cache.
	 *
	 * @param WP_REST_Response $response Odpowiedź.
	 * @return WP_REST_Response
	 */
	private static function no_cache( $response ) {
		$response->header( 'Cache-Control', 'no-store, max-age=0' );
		return $response;
	}
}
