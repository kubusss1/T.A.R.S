<?php
/**
 * Strona ustawień: Ustawienia → TARS Bridge.
 *
 * @package TARS_Bridge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Panel administracyjny wtyczki.
 */
final class TARS_Bridge_Admin {

	const PAGE          = 'tars-bridge';
	const ACTION_REGEN  = 'tars_bridge_regenerate_key';
	const SETTINGS_GRP  = 'tars_bridge_settings_group';

	/**
	 * Podpina hooki.
	 */
	public static function register() {
		add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
		add_action( 'admin_init', array( __CLASS__, 'register_settings' ) );
		add_action( 'admin_post_' . self::ACTION_REGEN, array( __CLASS__, 'handle_regenerate' ) );
		add_filter( 'plugin_action_links_' . plugin_basename( TARS_BRIDGE_FILE ), array( __CLASS__, 'action_links' ) );
	}

	/**
	 * Pozycja w menu Ustawienia.
	 */
	public static function menu() {
		add_options_page(
			__( 'TARS Bridge', 'tars-bridge' ),
			__( 'TARS Bridge', 'tars-bridge' ),
			'manage_options',
			self::PAGE,
			array( __CLASS__, 'render' )
		);
	}

	/**
	 * Link "Ustawienia" na liście wtyczek.
	 *
	 * @param array $links Linki.
	 * @return array
	 */
	public static function action_links( $links ) {
		$url = admin_url( 'options-general.php?page=' . self::PAGE );
		array_unshift( $links, '<a href="' . esc_url( $url ) . '">' . esc_html__( 'Ustawienia', 'tars-bridge' ) . '</a>' );
		return $links;
	}

	/**
	 * Rejestracja ustawień (Settings API).
	 */
	public static function register_settings() {
		register_setting(
			self::SETTINGS_GRP,
			TARS_Bridge_DB::OPT_SETTINGS,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( __CLASS__, 'sanitize_settings' ),
				'default'           => TARS_Bridge_DB::default_settings(),
			)
		);
	}

	/**
	 * Sanityzacja ustawień.
	 *
	 * @param mixed $input Dane z formularza.
	 * @return array
	 */
	public static function sanitize_settings( $input ) {
		$input = is_array( $input ) ? $input : array();
		return array(
			'tracking'    => empty( $input['tracking'] ) ? 0 : 1,
			'respect_dnt' => empty( $input['respect_dnt'] ) ? 0 : 1,
		);
	}

	/**
	 * Obsługa przycisku "Wygeneruj nowy klucz".
	 */
	public static function handle_regenerate() {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Brak uprawnień.', 'tars-bridge' ), 403 );
		}
		check_admin_referer( self::ACTION_REGEN );
		update_option( TARS_Bridge_DB::OPT_KEY, TARS_Bridge_DB::generate_key(), false );
		wp_safe_redirect(
			add_query_arg(
				array(
					'page'            => self::PAGE,
					'tars_regenerated' => '1',
				),
				admin_url( 'options-general.php' )
			)
		);
		exit;
	}

	/**
	 * Liczba odsłon z ostatnich 24 godzin (informacyjnie).
	 *
	 * @return int
	 */
	private static function hits_last_day() {
		global $wpdb;
		$table = TARS_Bridge_DB::hits_table();
		$since = gmdate( 'Y-m-d H:i:s', current_time( 'timestamp' ) - DAY_IN_SECONDS ); // phpcs:ignore WordPress.DateTime.CurrentTimeTimestamp.Requested
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared, WordPress.DB.DirectDatabaseQuery -- nazwa tabeli stała.
		return (int) $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$table} WHERE created_at >= %s", $since ) );
	}

	/**
	 * Render strony ustawień.
	 */
	public static function render() {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Brak uprawnień.', 'tars-bridge' ), 403 );
		}
		$key      = TARS_Bridge_DB::api_key();
		$settings = TARS_Bridge_DB::settings();
		$regen    = isset( $_GET['tars_regenerated'] ); // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- tylko komunikat.
		$example  = wp_json_encode(
			array(
				'name' => wp_specialchars_decode( get_bloginfo( 'name' ), ENT_QUOTES ),
				'url'  => home_url(),
				'key'  => $key,
			),
			JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
		);
		$endpoints = array(
			'GET /status'     => rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/status' ),
			'GET /analytics'  => rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/analytics' ) . '?days=30',
			'POST /hit'       => rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/hit' ),
			'POST /consent'   => rest_url( TARS_Bridge_REST::NAMESPACE_V1 . '/consent' ),
		);
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'TARS Bridge', 'tars-bridge' ); ?></h1>
			<p><?php esc_html_e( 'Łączy tę stronę z panelem TARS (ZrobSite): status, aktualizacje, SSL oraz anonimowa analityka odwiedzin i zgód cookie. Adresy IP nie są zapisywane.', 'tars-bridge' ); ?></p>

			<?php if ( $regen ) : ?>
				<div class="notice notice-success is-dismissible"><p><?php esc_html_e( 'Wygenerowano nowy klucz API. Zaktualizuj go w pliku sites.json w TARS.', 'tars-bridge' ); ?></p></div>
			<?php endif; ?>

			<h2><?php esc_html_e( 'Klucz API', 'tars-bridge' ); ?></h2>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="tars-bridge-key"><?php esc_html_e( 'Klucz (nagłówek X-TARS-Key)', 'tars-bridge' ); ?></label></th>
					<td>
						<input type="text" id="tars-bridge-key" class="regular-text code" readonly value="<?php echo esc_attr( $key ); ?>" onclick="this.select();" />
						<button type="button" class="button" onclick="var i=document.getElementById('tars-bridge-key');i.select();if(navigator.clipboard){navigator.clipboard.writeText(i.value);}else{document.execCommand('copy');}this.textContent='<?php echo esc_js( __( 'Skopiowano', 'tars-bridge' ) ); ?>';"><?php esc_html_e( 'Kopiuj', 'tars-bridge' ); ?></button>
						<p class="description"><?php esc_html_e( 'Traktuj klucz jak hasło. Wklej go do pliku sites.json w TARS.', 'tars-bridge' ); ?></p>
					</td>
				</tr>
			</table>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" onsubmit="return confirm('<?php echo esc_js( __( 'Na pewno? Stary klucz przestanie działać.', 'tars-bridge' ) ); ?>');">
				<input type="hidden" name="action" value="<?php echo esc_attr( self::ACTION_REGEN ); ?>" />
				<?php wp_nonce_field( self::ACTION_REGEN ); ?>
				<?php submit_button( __( 'Wygeneruj nowy klucz', 'tars-bridge' ), 'secondary', 'submit', false ); ?>
			</form>

			<h2><?php esc_html_e( 'Wpis do sites.json', 'tars-bridge' ); ?></h2>
			<pre style="background:#fff;border:1px solid #c3c4c7;padding:12px;max-width:640px;overflow:auto;"><?php echo esc_html( (string) $example ); ?></pre>

			<h2><?php esc_html_e( 'Adresy endpointów', 'tars-bridge' ); ?></h2>
			<table class="widefat striped" style="max-width:860px;">
				<tbody>
				<?php foreach ( $endpoints as $label => $url ) : ?>
					<tr>
						<td style="width:140px;"><code><?php echo esc_html( $label ); ?></code></td>
						<td><code><?php echo esc_html( $url ); ?></code></td>
					</tr>
				<?php endforeach; ?>
				</tbody>
			</table>

			<h2><?php esc_html_e( 'Analityka', 'tars-bridge' ); ?></h2>
			<form method="post" action="options.php">
				<?php settings_fields( self::SETTINGS_GRP ); ?>
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row"><?php esc_html_e( 'Śledzenie odwiedzin', 'tars-bridge' ); ?></th>
						<td>
							<label><input type="checkbox" name="<?php echo esc_attr( TARS_Bridge_DB::OPT_SETTINGS ); ?>[tracking]" value="1" <?php checked( ! empty( $settings['tracking'] ) ); ?> />
							<?php esc_html_e( 'Zbieraj anonimowe odsłony i statystyki zgód (bez cookies, bez IP)', 'tars-bridge' ); ?></label>
						</td>
					</tr>
					<tr>
						<th scope="row"><?php esc_html_e( 'Do Not Track', 'tars-bridge' ); ?></th>
						<td>
							<label><input type="checkbox" name="<?php echo esc_attr( TARS_Bridge_DB::OPT_SETTINGS ); ?>[respect_dnt]" value="1" <?php checked( ! empty( $settings['respect_dnt'] ) ); ?> />
							<?php esc_html_e( 'Nie licz odwiedzających z włączonym „Do Not Track”', 'tars-bridge' ); ?></label>
						</td>
					</tr>
				</table>
				<p class="description">
					<?php
					/* translators: %d: liczba odsłon. */
					echo esc_html( sprintf( __( 'Odsłony z ostatnich 24 godzin: %d. Dane starsze niż 180 dni są usuwane automatycznie.', 'tars-bridge' ), self::hits_last_day() ) );
					?>
				</p>
				<?php submit_button( __( 'Zapisz ustawienia', 'tars-bridge' ) ); ?>
			</form>
		</div>
		<?php
	}
}
