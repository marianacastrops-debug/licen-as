-- WorkLive emergency hardening for live_remote_control.
-- Run this in the Supabase SQL editor after rotating the leaked service_role key.

begin;

create or replace function public.il_cliente_enviar_comando(
  p_chave text,
  p_device_uuid text,
  p_command text,
  p_config jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_lic public.licencas%rowtype;
  v_dev public.licenca_devices%rowtype;
  v_next bigint;
  v_allowed text[] := array[
    'start_cycle',
    'stop_cycle',
    'coupon_on',
    'coupon_off',
    'fixar_on',
    'fixar_off',
    'block_on',
    'block_off',
    'comments_on',
    'comments_off',
    'encerrar_live',
    'tirar_print',
    'set_saudacao',
    'testar_saudacao',
    'responder_comentario',
    'sync_now',
    'history_sync',
    'ra_set_config',
    'ra_start',
    'ra_stop'
  ];
begin
  p_chave := upper(trim(coalesce(p_chave, '')));
  p_device_uuid := trim(coalesce(p_device_uuid, ''));
  p_command := trim(coalesce(p_command, ''));

  if p_chave = '' or p_device_uuid = '' or p_command = '' then
    return jsonb_build_object('ok', false, 'msg', 'Dados incompletos.');
  end if;

  if not (p_command = any(v_allowed)) then
    return jsonb_build_object('ok', false, 'msg', 'Comando nao permitido.');
  end if;

  select *
    into v_lic
    from public.licencas
   where chave = p_chave
   limit 1;

  if not found then
    return jsonb_build_object('ok', false, 'msg', 'Licenca nao encontrada.');
  end if;

  if coalesce(v_lic.ativa, false) is not true then
    return jsonb_build_object('ok', false, 'msg', 'Licenca inativa.');
  end if;

  if v_lic.expira_em is not null and v_lic.expira_em < now() then
    return jsonb_build_object('ok', false, 'msg', 'Licenca expirada.');
  end if;

  select *
    into v_dev
    from public.licenca_devices
   where licenca_id = v_lic.id
     and device_uuid = p_device_uuid
   limit 1;

  if not found then
    return jsonb_build_object('ok', false, 'msg', 'Dispositivo nao pertence a esta licenca.');
  end if;

  select coalesce(max(command_id), 0) + 1
    into v_next
    from public.live_remote_control
   where user_key = p_device_uuid;

  update public.live_remote_control
     set command = p_command,
         config = coalesce(p_config, '{}'::jsonb),
         command_id = v_next,
         updated_at = now()
   where user_key = p_device_uuid;

  if not found then
    insert into public.live_remote_control(user_key, command, config, command_id, updated_at)
    values (p_device_uuid, p_command, coalesce(p_config, '{}'::jsonb), v_next, now());
  end if;

  return jsonb_build_object('ok', true, 'command_id', v_next);
end;
$$;

create or replace function public.il_device_clear_command(p_device_uuid text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  p_device_uuid := trim(coalesce(p_device_uuid, ''));

  if p_device_uuid = '' then
    return jsonb_build_object('ok', false, 'msg', 'Dispositivo vazio.');
  end if;

  update public.live_remote_control
     set command = 'none',
         updated_at = now()
   where user_key = p_device_uuid;

  return jsonb_build_object('ok', true);
end;
$$;

revoke insert, update, delete on public.live_remote_control from anon, authenticated;
grant execute on function public.il_cliente_enviar_comando(text, text, text, jsonb) to anon, authenticated;
grant execute on function public.il_device_clear_command(text) to anon, authenticated;

-- Keep SELECT only if the extension still polls live_remote_control directly.
grant select on public.live_remote_control to anon, authenticated;

commit;
